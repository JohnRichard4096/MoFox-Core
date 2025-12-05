"""
用户画像更新工具

采用两阶段设计：
1. 工具调用模型(tool_use)负责判断是否需要更新，传入基本信息
2. 关系追踪模型(relationship_tracker)负责：
   - 读取最近聊天记录
   - 生成高质量的、有人设特色的印象内容
   - 决定好感度变化（联动更新）
"""

import time
from typing import Any, ClassVar

from sqlalchemy import select

from src.chat.utils.chat_message_builder import build_readable_messages
from src.common.database.compatibility import get_db_session
from src.common.database.core.models import UserRelationships
from src.common.logger import get_logger
from src.config.config import global_config, model_config  # type: ignore[attr-defined]
from src.plugin_system import BaseTool, ToolParamType

# 默认好感度分数，用于配置未初始化时的回退
DEFAULT_RELATIONSHIP_SCORE = 0.3

logger = get_logger("user_profile_tool")


def _get_base_relationship_score() -> float:
    """安全获取基础好感度分数"""
    if global_config and global_config.affinity_flow:
        return global_config.affinity_flow.base_relationship_score
    return DEFAULT_RELATIONSHIP_SCORE


class UserProfileTool(BaseTool):
    """用户画像更新工具

    两阶段设计：
    - 第一阶段：tool_use模型判断是否更新，传入简要信息
    - 第二阶段：relationship_tracker模型读取聊天记录，生成印象并决定好感度变化
    """

    name = "update_user_profile"
    description = """记录或更新你对某个人的认识。可以经常调用来保持印象的实时性。

使用场景：
1. TA告诉你个人信息（生日、职业、城市等）→ 填 key_info_type 和 key_info_value
2. TA的信息有变化（搬家、换工作等）→ 会自动更新旧信息
3. 你对TA有了新的认识或感受
4. 想更新对TA的印象

⚠️ 注意：TA讲的游戏剧情/故事不是TA本人的信息，不要记录虚构内容。
此工具在后台异步执行，不影响回复速度。"""
    parameters:ClassVar = [
        ("target_user_id", ToolParamType.STRING, "目标用户的ID（必须）", True, None),
        ("target_user_name", ToolParamType.STRING, "目标用户的名字/昵称（必须）", True, None),
        ("user_aliases", ToolParamType.STRING, "TA的其他昵称或别名（可选）", False, None),
        ("impression_hint", ToolParamType.STRING, "你观察到的关于TA的要点（可选）", False, None),
        ("preference_keywords", ToolParamType.STRING, "TA的兴趣爱好关键词（可选）", False, None),
        (
            "key_info_type",
            ToolParamType.STRING,
            "信息类型：birthday/job/location/dream/family/pet（可选）",
            False,
            None,
        ),
        ("key_info_value", ToolParamType.STRING, "信息内容，如'11月23日'、'上海'（可选）", False, None),
    ]
    available_for_llm = True
    history_ttl = 1

    async def execute(self, function_args: dict[str, Any]) -> dict[str, Any]:
        """执行用户画像更新（异步后台执行，不阻塞回复）

        Args:
            function_args: 工具参数

        Returns:
            dict: 执行结果
        """
        import asyncio

        try:
            # 提取参数
            target_user_id = function_args.get("target_user_id")
            target_user_name = function_args.get("target_user_name", target_user_id)
            if not target_user_id:
                return {"type": "error", "id": "user_profile_update", "content": "错误：必须提供目标用户ID"}

            # 从LLM传入的参数
            new_aliases = function_args.get("user_aliases", "")
            impression_hint = function_args.get("impression_hint", "")
            new_keywords = function_args.get("preference_keywords", "")
            key_info_type = function_args.get("key_info_type", "")
            key_info_value = function_args.get("key_info_value", "")

            # 如果LLM没有传入任何有效参数，返回提示
            if not any([new_aliases, impression_hint, new_keywords, key_info_value]):
                return {
                    "type": "info",
                    "id": target_user_id,
                    "content": "提示：需要提供至少一项更新内容（别名、印象描述、偏好关键词或重要信息）",
                }

            # 🎯 异步后台执行，不阻塞回复
            asyncio.create_task(  # noqa: RUF006
                self._background_update(
                    target_user_id=target_user_id,
                    target_user_name=str(target_user_name) if target_user_name else str(target_user_id),
                    new_aliases=new_aliases,
                    impression_hint=impression_hint,
                    new_keywords=new_keywords,
                    key_info_type=key_info_type,
                    key_info_value=key_info_value,
                )
            )

            # 立即返回，让回复继续
            return {
                "type": "user_profile_update",
                "id": target_user_id,
                "content": f"正在后台更新对 {target_user_name} 的印象...",
            }

        except Exception as e:
            logger.error(f"用户画像更新失败: {e}")
            return {
                "type": "error",
                "id": function_args.get("target_user_id", "unknown"),
                "content": f"用户画像更新失败: {e!s}",
            }

    async def _background_update(
        self,
        target_user_id: str,
        target_user_name: str,
        new_aliases: str,
        impression_hint: str,
        new_keywords: str,
        key_info_type: str = "",
        key_info_value: str = "",
    ):
        """后台执行用户画像更新"""
        try:
            # 从数据库获取现有用户画像
            existing_profile = await self._get_user_profile(target_user_id)

            # 🎯 如果有关键信息，先保存（生日、职业等重要信息）
            if key_info_value:
                await self._add_key_fact(target_user_id, key_info_type or "other", key_info_value)
                logger.info(f"[后台] 已记录关键信息: {target_user_id}, {key_info_type}={key_info_value}")

            # 获取最近的聊天记录
            chat_history_text = await self._get_recent_chat_history(target_user_id)

            # 🎯 核心：使用relationship_tracker模型生成印象并决定好感度变化
            final_impression = existing_profile.get("relationship_text", "")
            affection_change = 0.0  # 好感度变化量

            if impression_hint or chat_history_text:
                impression_result = await self._generate_impression_with_affection(
                    target_user_name=target_user_name,
                    impression_hint=impression_hint,
                    existing_impression=str(existing_profile.get("relationship_text", "")),
                    preference_keywords=str(new_keywords or existing_profile.get("preference_keywords", "")),
                    chat_history=chat_history_text,
                    current_score=float(existing_profile.get("relationship_score", _get_base_relationship_score())),
                )
                final_impression = impression_result.get("impression", final_impression)
                affection_change = impression_result.get("affection_change", 0.0)

            # 计算新的好感度
            old_score = float(existing_profile.get("relationship_score", _get_base_relationship_score()))
            new_score = old_score + affection_change
            new_score = max(0.0, min(1.0, new_score))  # 确保在0-1范围内

            # 构建最终画像
            final_profile = {
                "user_aliases": new_aliases if new_aliases else existing_profile.get("user_aliases", ""),
                "relationship_text": final_impression,
                "preference_keywords": new_keywords
                if new_keywords
                else existing_profile.get("preference_keywords", ""),
                "relationship_score": new_score,
            }

            # 更新数据库
            await self._update_user_profile_in_db(target_user_id, final_profile)

            logger.info(f"[后台] 用户画像更新成功: {target_user_id}, 好感度变化: {affection_change:+.2f}")

        except Exception as e:
            logger.error(f"[后台] 用户画像更新失败: {e}")

    async def _add_key_fact(self, user_id: str, info_type: str, info_value: str):
        """添加或更新关键信息（生日、职业等）

        Args:
            user_id: 用户ID
            info_type: 信息类型（birthday/job/location/dream/family/pet/other）
            info_value: 信息内容
        """
        import orjson

        try:
            # 验证 info_type
            valid_types = ["birthday", "job", "location", "dream", "family", "pet", "other"]
            if info_type not in valid_types:
                info_type = "other"

            current_time = time.time()

            async with get_db_session() as session:
                stmt = select(UserRelationships).where(UserRelationships.user_id == user_id)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # 解析现有的 key_facts
                    try:
                        facts = orjson.loads(existing.key_facts) if existing.key_facts else []
                    except Exception:
                        facts = []

                    if not isinstance(facts, list):
                        facts = []

                    # 查找是否已有相同类型的信息
                    found = False
                    for i, fact in enumerate(facts):
                        if isinstance(fact, dict) and fact.get("type") == info_type:
                            # 更新现有记录
                            facts[i] = {"type": info_type, "value": info_value}
                            found = True
                            break

                    if not found:
                        # 添加新记录
                        facts.append({"type": info_type, "value": info_value})

                    # 更新数据库
                    existing.key_facts = orjson.dumps(facts).decode("utf-8")
                    existing.last_updated = current_time
                else:
                    # 创建新用户记录
                    facts = [{"type": info_type, "value": info_value}]
                    new_profile = UserRelationships(
                        user_id=user_id,
                        user_name=user_id,
                        key_facts=orjson.dumps(facts).decode("utf-8"),
                        first_met_time=current_time,
                        last_updated=current_time,
                    )
                    session.add(new_profile)

                await session.commit()

                # 清除缓存，确保下次查询获取最新数据
                try:
                    from src.common.database.optimization.cache_manager import get_cache

                    cache = await get_cache()
                    cache_key = f"user_relationships:filter:[('user_id', '{user_id}')]"
                    await cache.delete(cache_key)
                    logger.debug(f"已清除用户关系缓存: {user_id}")
                except Exception as cache_err:
                    logger.warning(f"清除缓存失败（不影响数据保存）: {cache_err}")

                logger.info(f"关键信息已保存: {user_id}, {info_type}={info_value}")

        except Exception as e:
            logger.error(f"保存关键信息失败: {e}")
            # 不抛出异常，因为这是后台任务

    async def _get_recent_chat_history(self, target_user_id: str, max_messages: int = 50) -> str:
        """获取最近的聊天记录

        Args:
            target_user_id: 目标用户ID
            max_messages: 最大消息数量

        Returns:
            str: 格式化的聊天记录文本
        """
        try:
            # 从 chat_stream 获取上下文
            if not self.chat_stream:
                logger.warning("chat_stream 未初始化，无法获取聊天记录")
                return ""

            context = getattr(self.chat_stream, "context", None)
            if not context:
                logger.warning("chat_stream.context 不存在，无法获取聊天记录")
                return ""

            # 获取最近的消息 - 使用正确的方法名 get_messages
            messages = context.get_messages(limit=max_messages, include_unread=True)
            if not messages:
                return ""

            # 将 DatabaseMessages 对象转换为字典列表
            messages_dict = []
            for msg in messages:
                try:
                    if hasattr(msg, "to_dict"):
                        messages_dict.append(msg.to_dict())
                    elif hasattr(msg, "__dict__"):
                        # 手动构建字典
                        msg_dict = {
                            "time": getattr(msg, "time", 0),
                            "processed_plain_text": getattr(msg, "processed_plain_text", ""),
                            "display_message": getattr(msg, "display_message", ""),
                        }
                        # 处理 user_info
                        user_info = getattr(msg, "user_info", None)
                        if user_info:
                            msg_dict["user_info"] = {
                                "user_id": getattr(user_info, "user_id", ""),
                                "user_nickname": getattr(user_info, "user_nickname", ""),
                            }
                        # 处理 chat_info
                        chat_info = getattr(msg, "chat_info", None)
                        if chat_info:
                            msg_dict["chat_info"] = {
                                "platform": getattr(chat_info, "platform", ""),
                            }
                        messages_dict.append(msg_dict)
                except Exception as e:
                    logger.warning(f"转换消息失败: {e}")
                    continue

            if not messages_dict:
                return ""

            # 构建可读的消息文本
            readable_messages = await build_readable_messages(
                messages=messages_dict, replace_bot_name=True, timestamp_mode="normal_no_YMD", truncate=True
            )

            return readable_messages or ""

        except Exception as e:
            logger.error(f"获取聊天记录失败: {e}")
            return ""

    async def _generate_impression_with_affection(
        self,
        target_user_name: str,
        impression_hint: str,
        existing_impression: str,
        preference_keywords: str,
        chat_history: str,
        current_score: float,
    ) -> dict[str, Any]:
        """使用relationship_tracker模型生成印象并决定好感度变化

        Args:
            target_user_name: 目标用户的名字
            impression_hint: 工具调用模型传入的简要观察
            existing_impression: 现有的印象描述
            preference_keywords: 用户的兴趣偏好
            chat_history: 最近的聊天记录
            current_score: 当前好感度分数

        Returns:
            dict: {"impression": str, "affection_change": float}
        """
        try:
            import orjson
            from json_repair import repair_json
            from src.llm_models.utils_model import LLMRequest

            # 获取人设信息（添加空值保护）
            bot_name = global_config.bot.nickname if global_config and global_config.bot else "Bot"
            personality_core = (
                global_config.personality.personality_core if global_config and global_config.personality else ""
            )
            personality_side = (
                global_config.personality.personality_side if global_config and global_config.personality else ""
            )
            reply_style = global_config.personality.reply_style if global_config and global_config.personality else ""

            # 构建提示词
            # 根据是否有旧印象决定任务类型
            is_first_impression = not existing_impression or len(existing_impression) < 20

            prompt = f"""你是{bot_name}，现在要记录你对"{target_user_name}"的印象。

## 你的核心人格
{personality_core}

## 你的性格侧面
{personality_side}

## 你的说话风格
{reply_style}

## 你之前对{target_user_name}的印象
{existing_impression if existing_impression else "（这是你第一次记录对TA的印象）"}

## 最近的聊天记录
{chat_history if chat_history else "（无聊天记录）"}

## 这次观察到的新要点
{impression_hint if impression_hint else "（无特别观察）"}

## {target_user_name}的兴趣爱好
{preference_keywords if preference_keywords else "暂未了解"}

## 当前好感度
{current_score:.2f} (范围0-1，0.3=普通认识，0.5=朋友，0.7=好友，0.9=挚友)

## ⚠️ 重要：区分虚构内容和真实信息
- 如果{target_user_name}在讲述**游戏剧情、小说情节、动漫故事、角色扮演**等虚构内容，这些是**TA分享的内容**，不是TA本人的特质
- 印象应该记录的是**{target_user_name}这个人**的特点，比如：
  - TA喜欢玩什么游戏、看什么动漫（兴趣）
  - TA讲故事时的语气和热情（性格）
  - TA和你交流时的方式（互动风格）
- **不要**把游戏里的角色、剧情、NPC的特点当成{target_user_name}本人的特点
- 例如：如果TA在讲游戏里的剧情，记录的应该是"TA很喜欢这个游戏/对剧情很有感触"

## 任务
1. 根据聊天记录判断{target_user_name}的性别（男用"他"，女用"她"，无法判断用名字）
2. {"写下你对这个人的第一印象" if is_first_impression else "在原有印象基础上，融入新的观察"}
3. 决定好感度是否需要变化（大多数情况不需要）

## 印象写作要求（重要！）
这是**长期印象**，不是某次聊天的记录！

**应该写的（泛化、抽象）：**
- TA是什么样的人（性格特点）
- TA给你的整体感觉
- TA的说话风格、互动方式
- TA的兴趣爱好类型
- 你们关系的整体状态

**不要写的（太具体、太短期）：**
- ❌ "今天TA跟我聊了xxx"
- ❌ "TA刚才说了xxx"
- ❌ 具体的某一次对话内容
- ❌ 某个具体事件的细节
- ❌ 时间词如"刚才"、"今天"、"最近一次"

**格式要求：**
- 用第一人称"我"来写
- 根据判断的性别使用"他/她"
- {"第一印象50-150字" if is_first_impression else "150-300字，在原有基础上补充"}
- 写出这个人的**整体特质**，而不是某次聊天的具体内容

## 好感度变化规则（极其严格！99%的对话好感度不变！）

**核心原则：好感度是长期关系的体现，不是单次对话能改变的。**

- 范围：-0.02 到 +0.02，**但绝大多数情况应该是 0**
- 好感度会自然波动，即使很高也可能因为疏远、冷淡、误解而下降

**好感度 = 0（不变）的情况（这是默认值！）：**
- 普通聊天、日常问候、闲聊 → 0
- 聊得很开心、话题很有趣 → 0（开心≠好感增加）
- 讨论游戏、分享故事、聊兴趣 → 0
- 对方表达喜欢你、夸你 → 0（嘴上说的不算数）
- 简单的关心、问候 → 0
- 友好的互动 → 0（友好是正常的，不是加分项）

**好感度 = +0.01（微涨）的情况（非常罕见）：**
- 对方在真正困难时向你倾诉，展现了深层信任
- 经过很长时间的相处，关系有了质的突破

**好感度 = +0.02（涨）的情况（极其罕见，几乎不会发生）：**
- 对方为你做出了实质性的牺牲或帮助
- 你们之间发生了真正改变关系的重大事件

**好感度 = -0.01 到 -0.02（下降）的情况：**
- 对方明显冷淡、敷衍
- 发生了误解或小冲突
- 长时间不联系后的疏远感

**记住：**
1. 聊得开心 ≠ 好感增加
2. 话题友好 ≠ 好感增加  
3. 对方说喜欢你 ≠ 好感增加
4. 好感是需要很长时间才能培养的
5. 如果你不确定，就填 0

请严格按照以下JSON格式输出：
{{
    "gender": "male/female/unknown",
    "impression": "你对{target_user_name}的印象...",
    "affection_change": 0,
    "change_reason": "无变化/变化原因"
}}"""

            # 使用relationship_tracker模型（添加空值保护）
            if not model_config or not model_config.model_task_config:
                raise ValueError("model_config 未初始化")

            llm = LLMRequest(
                model_set=model_config.model_task_config.relationship_tracker,
                request_type="user_profile.impression_and_affection",
            )

            response, _ = await llm.generate_response_async(
                prompt=prompt,
                temperature=0.7,
                max_tokens=600,
            )

            # 解析响应
            response = response.strip()
            try:
                result = orjson.loads(repair_json(response))
                impression = result.get("impression", "")
                affection_change = float(result.get("affection_change", 0))
                change_reason = result.get("change_reason", "")
                detected_gender = result.get("gender", "unknown")

                # 限制好感度变化范围（极严格：-0.02 到 +0.02）
                affection_change = max(-0.02, min(0.02, affection_change))

                # 如果印象为空或太短，回退到hint
                if not impression or len(impression) < 10:
                    logger.warning(f"印象生成结果过短，使用原始hint")
                    impression = impression_hint or existing_impression

                logger.info(f"印象更新: 用户性别判断={detected_gender}, 好感度变化={affection_change:+.3f}")
                if change_reason:
                    logger.info(f"好感度变化原因: {change_reason}")

                return {"impression": impression, "affection_change": affection_change}

            except Exception as parse_error:
                logger.warning(f"解析JSON失败: {parse_error}，尝试提取文本")
                # 如果JSON解析失败，尝试直接使用响应作为印象
                return {
                    "impression": response if len(response) > 10 else (impression_hint or existing_impression),
                    "affection_change": 0.0,
                }

        except Exception as e:
            logger.error(f"生成印象和好感度失败: {e}")
            # 失败时回退
            return {"impression": impression_hint or existing_impression, "affection_change": 0.0}

    async def _get_user_profile(self, user_id: str) -> dict[str, Any]:
        """从数据库获取用户现有画像

        Args:
            user_id: 用户ID

        Returns:
            dict: 用户画像数据
        """
        try:
            async with get_db_session() as session:
                stmt = select(UserRelationships).where(UserRelationships.user_id == user_id)
                result = await session.execute(stmt)
                profile = result.scalar_one_or_none()

                if profile:
                    # 优先使用新字段 impression_text，如果没有则用旧字段 relationship_text
                    impression = profile.impression_text or profile.relationship_text or ""
                    return {
                        "user_name": profile.user_name or user_id,
                        "user_aliases": profile.user_aliases or "",
                        "relationship_text": impression,  # 兼容旧代码
                        "impression_text": impression,
                        "preference_keywords": profile.preference_keywords or "",
                        "key_facts": profile.key_facts or "[]",
                        "relationship_score": float(profile.relationship_score)
                        if profile.relationship_score is not None
                        else _get_base_relationship_score(),
                        "relationship_stage": profile.relationship_stage or "stranger",
                        "first_met_time": profile.first_met_time,
                    }
                else:
                    # 用户不存在，返回默认值
                    return {
                        "user_name": user_id,
                        "user_aliases": "",
                        "relationship_text": "",
                        "impression_text": "",
                        "preference_keywords": "",
                        "key_facts": "[]",
                        "relationship_score": _get_base_relationship_score(),
                        "relationship_stage": "stranger",
                        "first_met_time": None,
                    }
        except Exception as e:
            logger.error(f"获取用户画像失败: {e}")
            return {
                "user_name": user_id,
                "user_aliases": "",
                "relationship_text": "",
                "impression_text": "",
                "preference_keywords": "",
                "key_facts": "[]",
                "relationship_score": _get_base_relationship_score(),
                "relationship_stage": "stranger",
                "first_met_time": None,
            }

    async def _update_user_profile_in_db(self, user_id: str, profile: dict[str, Any]):
        """更新数据库中的用户画像

        Args:
            user_id: 用户ID
            profile: 画像数据
        """
        try:
            current_time = time.time()

            async with get_db_session() as session:
                stmt = select(UserRelationships).where(UserRelationships.user_id == user_id)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                # 根据好感度自动计算关系阶段
                score = profile.get("relationship_score", 0.3)
                stage = self._calculate_relationship_stage(score)

                if existing:
                    # 更新现有记录
                    existing.user_aliases = profile.get("user_aliases", "")
                    # 同时更新新旧两个印象字段，保持兼容
                    impression = profile.get("relationship_text", "")
                    existing.relationship_text = impression
                    existing.impression_text = impression
                    existing.preference_keywords = profile.get("preference_keywords", "")
                    existing.relationship_score = score
                    existing.relationship_stage = stage
                    existing.last_impression_update = current_time
                    existing.last_updated = current_time
                    # 如果是首次认识，记录时间
                    if not existing.first_met_time:
                        existing.first_met_time = current_time
                else:
                    # 创建新记录
                    impression = profile.get("relationship_text", "")
                    new_profile = UserRelationships(
                        user_id=user_id,
                        user_name=user_id,
                        user_aliases=profile.get("user_aliases", ""),
                        relationship_text=impression,
                        impression_text=impression,
                        preference_keywords=profile.get("preference_keywords", ""),
                        relationship_score=score,
                        relationship_stage=stage,
                        first_met_time=current_time,
                        last_impression_update=current_time,
                        last_updated=current_time,
                    )
                    session.add(new_profile)

                await session.commit()

                # 清除缓存，确保下次查询获取最新数据
                try:
                    from src.common.database.optimization.cache_manager import get_cache

                    cache = await get_cache()
                    cache_key = f"user_relationships:filter:[('user_id', '{user_id}')]"
                    await cache.delete(cache_key)
                    logger.debug(f"已清除用户关系缓存: {user_id}")
                except Exception as cache_err:
                    logger.warning(f"清除缓存失败（不影响数据保存）: {cache_err}")

                logger.info(f"用户画像已更新到数据库: {user_id}, 阶段: {stage}")

        except Exception as e:
            logger.error(f"更新用户画像到数据库失败: {e}")
            raise

    def _calculate_relationship_stage(self, score: float) -> str:
        """根据好感度分数计算关系阶段

        Args:
            score: 好感度分数(0-1)

        Returns:
            str: 关系阶段
        """
        if score >= 0.9:
            return "bestie"  # 挚友
        elif score >= 0.75:
            return "close_friend"  # 好友
        elif score >= 0.6:
            return "friend"  # 朋友
        elif score >= 0.4:
            return "familiar"  # 熟人
        elif score >= 0.2:
            return "acquaintance"  # 初识
        else:
            return "stranger"  # 陌生人

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
from typing import Any

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
    description = """记录或更新你对某个人的认识。

使用场景：
1. TA告诉你个人信息（生日、职业、城市等）→ 填 key_info_type 和 key_info_value
2. TA的信息有变化（搬家、换工作等）→ 会自动更新旧信息
3. 你对TA有了新的认识或感受
4. 想更新对TA的印象

⚠️ 重要注意：
- 别名必须是TA自己明确表示想被这样称呼的（如"你叫我xx吧"、"我的昵称是xx"）
- 短期的撤娇/玩笑称呼不是别名（如"哈哈我是小笨蛋"这种玩笑不算）
- 关键信息必须是具体值（如"11月23日"），不要填描述性文字
- 游戏剧情/故事不是TA本人的信息

此工具在后台异步执行，不影响回复速度。"""
    parameters = [
        ("target_user_id", ToolParamType.STRING, "目标用户的ID（必须）", True, None),
        ("target_user_name", ToolParamType.STRING, "目标用户的名字/昵称（必须）", True, None),
        ("alias_operation", ToolParamType.STRING, "别名操作：add=新增 / remove=删除 / replace=全部替换（可选）", False, None),
        ("alias_value", ToolParamType.STRING, "别名内容，多个用、分隔", False, None),
        ("impression_hint", ToolParamType.STRING, "你观察到的关于TA的要点（可选）", False, None),
        ("preference_operation", ToolParamType.STRING, "偏好操作：add=新增 / remove=删除 / replace=全部替换（可选）", False, None),
        ("preference_value", ToolParamType.STRING, "偏好关键词，多个用、分隔（可选）", False, None),
        ("key_info_type", ToolParamType.STRING, "信息类型：birthday/job/location/dream/family/pet（可选）", False, None),
        ("key_info_value", ToolParamType.STRING, "具体信息内容（必须是具体值如'11月23日'、'上海'）", False, None),
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
                return {
                    "type": "error",
                    "id": "user_profile_update",
                    "content": "错误：必须提供目标用户ID"
                }

            # 从LLM传入的参数
            alias_operation = function_args.get("alias_operation", "")
            alias_value = function_args.get("alias_value", "")
            impression_hint = function_args.get("impression_hint", "")
            preference_operation = function_args.get("preference_operation", "")
            preference_value = function_args.get("preference_value", "")
            key_info_type = function_args.get("key_info_type", "")
            key_info_value = function_args.get("key_info_value", "")

            # 如果LLM没有传入任何有效参数，返回提示
            if not any([alias_value, impression_hint, preference_value, key_info_value]):
                return {
                    "type": "info",
                    "id": target_user_id,
                    "content": "提示：需要提供至少一项更新内容（别名、印象描述、偏好关键词或重要信息）"
                }

            # 🎯 异步后台执行，不阻塞回复
            asyncio.create_task(self._background_update(
                target_user_id=target_user_id,
                target_user_name=str(target_user_name) if target_user_name else str(target_user_id),
                alias_operation=alias_operation,
                alias_value=alias_value,
                impression_hint=impression_hint,
                preference_operation=preference_operation,
                preference_value=preference_value,
                key_info_type=key_info_type,
                key_info_value=key_info_value,
            ))

            # 立即返回，让回复继续
            return {
                "type": "user_profile_update",
                "id": target_user_id,
                "content": f"正在后台更新对 {target_user_name} 的印象..."
            }

        except Exception as e:
            logger.error(f"用户画像更新失败: {e}")
            return {
                "type": "error",
                "id": function_args.get("target_user_id", "unknown"),
                "content": f"用户画像更新失败: {e!s}"
            }

    async def _background_update(
        self,
        target_user_id: str,
        target_user_name: str,
        alias_operation: str,
        alias_value: str,
        impression_hint: str,
        preference_operation: str,
        preference_value: str,
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

            # 🎯 处理别名操作
            final_aliases = self._process_list_operation(
                existing_value=existing_profile.get("user_aliases", ""),
                operation=alias_operation,
                new_value=alias_value,
            )
            
            # 🎯 处理偏好操作
            final_preferences = self._process_list_operation(
                existing_value=existing_profile.get("preference_keywords", ""),
                operation=preference_operation,
                new_value=preference_value,
            )

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
                    preference_keywords=final_preferences,
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
                "user_aliases": final_aliases,
                "relationship_text": final_impression,
                "preference_keywords": final_preferences,
                "relationship_score": new_score,
            }

            # 更新数据库
            await self._update_user_profile_in_db(target_user_id, final_profile)

            logger.info(f"[后台] 用户画像更新成功: {target_user_id}, 好感度变化: {affection_change:+.2f}")

        except Exception as e:
            logger.error(f"[后台] 用户画像更新失败: {e}")
    
    def _process_list_operation(self, existing_value: str, operation: str, new_value: str) -> str:
        """处理列表类型的操作（别名、偏好等）
        
        Args:
            existing_value: 现有值（用、分隔）
            operation: 操作类型 add/remove/replace
            new_value: 新值（用、分隔）
            
        Returns:
            str: 处理后的值
        """
        if not new_value:
            return existing_value
        
        # 解析现有值和新值
        existing_set = set(filter(None, [x.strip() for x in (existing_value or "").split("、")]))
        new_set = set(filter(None, [x.strip() for x in new_value.split("、")]))
        
        operation = (operation or "add").lower().strip()
        
        if operation == "replace":
            # 全部替换
            result_set = new_set
            logger.info(f"别名/偏好替换: {existing_set} -> {new_set}")
        elif operation == "remove":
            # 删除指定项
            result_set = existing_set - new_set
            logger.info(f"别名/偏好删除: {new_set} 从 {existing_set}")
        else:  # add 或默认
            # 新增（合并）
            result_set = existing_set | new_set
            logger.info(f"别名/偏好新增: {new_set} 到 {existing_set}")
        
        return "、".join(sorted(result_set))

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
            
            # 🎯 信息质量判断：过滤掉模糊的描述性内容
            low_quality_patterns = [
                "的生日", "的工作", "的位置", "的梦想", "的家人", "的宠物",
                "birthday", "job", "location", "unknown", "未知", "不知道",
                "affectionate", "friendly", "的信息", "某个", "一个"
            ]
            info_value_lower = info_value.lower().strip()
            
            # 如果值太短或包含低质量模式，跳过
            if len(info_value_lower) < 2:
                logger.warning(f"关键信息值太短，跳过: {info_value}")
                return
            
            for pattern in low_quality_patterns:
                if pattern in info_value_lower:
                    logger.warning(f"关键信息质量不佳，跳过: {info_type}={info_value}（包含'{pattern}'）")
                    return
            
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
                            old_value = fact.get("value", "")
                            # 🎯 智能判断：如果旧值更具体，不要用模糊值覆盖
                            if len(old_value) > len(info_value) and not any(p in old_value.lower() for p in low_quality_patterns):
                                logger.info(f"保留更具体的旧值: {info_type}='{old_value}'，跳过新值: '{info_value}'")
                                return
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
                        last_updated=current_time
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
                    if hasattr(msg, 'to_dict'):
                        messages_dict.append(msg.to_dict())
                    elif hasattr(msg, '__dict__'):
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
                messages=messages_dict,
                replace_bot_name=True,
                timestamp_mode="normal_no_YMD",
                truncate=True
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
            personality_core = global_config.personality.personality_core if global_config and global_config.personality else ""
            personality_side = global_config.personality.personality_side if global_config and global_config.personality else ""
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
- 游戏剧情、小说情节、角色扮演等虚构内容 ≠ TA本人的特质
- 印象记录的是**这个人本身**：TA的性格、TA喜欢什么、TA和你交流的方式
- 如果TA在讲游戏剧情，记录的应该是"TA对这类故事很有热情"而非剧情本身

## 任务
1. 判断{target_user_name}的性别（男用"他"，女用"她"，无法判断用名字）
2. {"写下你对这个人的第一印象" if is_first_impression else "在原有印象基础上，融入新的感受和理解"}
3. 决定好感度是否需要变化（大多数情况不需要）

## 📝 印象写作指南

**核心定位：这是你心中对这个人的画像，是你对TA的理解和感受，不是聊天日志。**

### 内容维度（自然融入，不要分点罗列）：
- **性格气质**：TA给你的整体感觉，是什么类型的人
- **交流风格**：TA说话的方式、语气特点、互动习惯
- **情感印记**：让你印象深刻的感受（不是具体事件）
- **关系状态**：你们现在的关系是怎样的，相处起来什么感觉

### 写作风格：
- 散文式叙述，像在心里默默描绘一个人
- 写感受和印象，不是记录"TA做了什么"
- 带着你对TA的情感去描述，有温度
- 可以用比喻、联想，自然流畅

### 绝对避免：
- 时间词："今天"、"刚才"、"上次"、"最近"
- 具体事件："TA跟我说了xxx"、"我们聊了xxx"
- 罗列格式："喜欢A、B、C"、"特点：1.xx 2.xx"
- 流水账式："首先...然后...最后..."

### 字数要求：
- {"初次印象：80-150字，写出第一感觉" if is_first_impression else "深化印象：200-400字，在原有基础上自然融入新的理解"}

## 好感度变化规则（分阶段，越高越难涨）

当前好感度：{current_score:.2f}

**关系阶段与增速：**
| 阶段 | 分数范围 | 单次变化范围 | 说明 |
|------|----------|--------------|------|
| 陌生→初识 | 0.0-0.3 | ±0.03~0.05 | 容易建立初步印象 |
| 初识→熟人 | 0.3-0.5 | ±0.02~0.04 | 逐渐熟悉的阶段 |
| 熟人→朋友 | 0.5-0.7 | ±0.01~0.03 | 需要更多互动积累 |
| 朋友→好友 | 0.7-0.85 | ±0.01~0.02 | 关系深化变慢 |
| 好友→挚友 | 0.85-1.0 | ±0.005~0.01 | 极难变化，需要重大事件 |

**加分情况（根据当前阶段选择合适幅度）：**
- 愉快的聊天、有来有往的互动 → 小幅+（低阶段更明显）
- 分享心情、倾诉烦恼 → 中幅+
- 主动关心、记得之前聊过的事 → 中幅+
- 深度交流、展现信任 → 较大+
- 在困难时寻求帮助或给予支持 → 大幅+

**减分情况：**
- 敷衍、冷淡的回应 → 小幅-
- 明显的不耐烦或忽视 → 中幅-
- 冲突、误解 → 较大-
- 长期不联系（关系会自然冷却）→ 缓慢-

**不变的情况：**
- 纯粹的信息询问（问时间、问天气等）
- 机械式的对话
- 无法判断情感倾向的中性交流

**注意：高好感度（>0.8）时要非常谨慎加分，友好互动在这个阶段是常态，不是加分项。**

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
                request_type="user_profile.impression_and_affection"
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
                
                # 🎯 根据当前好感度阶段限制变化范围
                if current_score < 0.3:
                    # 陌生→初识：±0.05
                    max_change = 0.05
                elif current_score < 0.5:
                    # 初识→熟人：±0.04
                    max_change = 0.04
                elif current_score < 0.7:
                    # 熟人→朋友：±0.03
                    max_change = 0.03
                elif current_score < 0.85:
                    # 朋友→好友：±0.02
                    max_change = 0.02
                else:
                    # 好友→挚友：±0.01
                    max_change = 0.01
                
                affection_change = max(-max_change, min(max_change, affection_change))
                
                # 如果印象为空或太短，回退到hint
                if not impression or len(impression) < 10:
                    logger.warning(f"印象生成结果过短，使用原始hint")
                    impression = impression_hint or existing_impression
                
                logger.info(f"印象更新: 用户性别判断={detected_gender}, 好感度变化={affection_change:+.3f}")
                if change_reason:
                    logger.info(f"好感度变化原因: {change_reason}")
                
                return {
                    "impression": impression,
                    "affection_change": affection_change
                }
                
            except Exception as parse_error:
                logger.warning(f"解析JSON失败: {parse_error}，尝试提取文本")
                # 如果JSON解析失败，尝试直接使用响应作为印象
                return {
                    "impression": response if len(response) > 10 else (impression_hint or existing_impression),
                    "affection_change": 0.0
                }
            
        except Exception as e:
            logger.error(f"生成印象和好感度失败: {e}")
            # 失败时回退
            return {
                "impression": impression_hint or existing_impression,
                "affection_change": 0.0
            }

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
                        "relationship_score": float(profile.relationship_score) if profile.relationship_score is not None else _get_base_relationship_score(),
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
                    # 别名和偏好已经在_background_update中处理好了，直接赋值
                    existing.user_aliases = profile.get("user_aliases", "") or existing.user_aliases
                    
                    # 同时更新新旧两个印象字段，保持兼容
                    impression = profile.get("relationship_text", "")
                    if impression:  # 只有有新印象才更新
                        existing.relationship_text = impression
                        existing.impression_text = impression
                    
                    # 偏好关键词已经在_background_update中处理好了，直接赋值
                    existing.preference_keywords = profile.get("preference_keywords", "") or existing.preference_keywords
                    
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
                        last_updated=current_time
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



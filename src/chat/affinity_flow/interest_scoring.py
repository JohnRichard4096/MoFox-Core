"""
兴趣度评分系统
基于多维度评分机制，包括兴趣匹配度、用户关系分、提及度和时间因子
现在使用embedding计算智能兴趣匹配
"""
import traceback
from typing import Dict, List, Any

from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.info_data_model import InterestScore
from src.chat.interest_system import bot_interest_manager
from src.common.logger import get_logger
from src.config.config import global_config

logger = get_logger("interest_scoring")


class InterestScoringSystem:
    """兴趣度评分系统"""

    def __init__(self):
        # 智能兴趣匹配配置
        self.use_smart_matching = True

        # 评分权重
        self.score_weights = {
            "interest_match": 0.5,    # 兴趣匹配度权重
            "relationship": 0.3,      # 关系分权重
            "mentioned": 0.2,         # 是否提及bot权重
        }

        # 评分阈值
        self.reply_threshold = 0.55    # 默认回复阈值
        self.mention_threshold = 0.3   # 提及阈值

        # 连续不回复概率提升
        self.no_reply_count = 0
        self.max_no_reply_count = 15
        self.probability_boost_per_no_reply = 0.01  # 每次不回复增加15%概率

        # 用户关系数据
        self.user_relationships: Dict[str, float] = {}  # user_id -> relationship_score

    async def calculate_interest_scores(self, messages: List[DatabaseMessages], bot_nickname: str) -> List[InterestScore]:
        """计算消息的兴趣度评分"""
        logger.info("🚀 开始计算消息兴趣度评分...")
        logger.info(f"📨 收到 {len(messages)} 条消息")

        # 通过 user_id 判断是否是用户消息（非机器人发送的消息）
        user_messages = [msg for msg in messages if str(msg.user_info.user_id) != str(global_config.bot.qq_account)]
        logger.info(f"👤 过滤出 {len(user_messages)} 条用户消息")

        scores = []
        for i, msg in enumerate(user_messages, 1):
            logger.info(f"📋 [{i}/{len(user_messages)}] 处理消息 ID: {msg.message_id}")
            score = await self._calculate_single_message_score(msg, bot_nickname)
            scores.append(score)

        logger.info(f"✅ 兴趣度评分计算完成，生成 {len(scores)} 个评分")
        return scores

    async def _calculate_single_message_score(self, message: DatabaseMessages, bot_nickname: str) -> InterestScore:
        """计算单条消息的兴趣度评分"""
        logger.info(f"🎯 计算消息 {message.message_id} 的兴趣度评分...")
        logger.debug(f"📝 消息长度: {len(message.processed_plain_text)} 字符")

        # 提取关键词（从数据库的反序列化字段）
        logger.debug("🔍 提取关键词...")
        keywords = self._extract_keywords_from_database(message)
        logger.debug(f"🏷️  提取到 {len(keywords)} 个关键词")

        # 1. 计算兴趣匹配度（现在是异步的）
        logger.debug("🧠 计算兴趣匹配度...")
        interest_match_score = await self._calculate_interest_match_score(message.processed_plain_text, keywords)
        logger.debug(f"📊 兴趣匹配度: {interest_match_score:.3f}")

        # 2. 计算关系分
        logger.debug("🤝 计算关系分...")
        relationship_score = self._calculate_relationship_score(message.user_info.user_id)
        logger.debug(f"💝 关系分: {relationship_score:.3f}")

        # 3. 计算提及分数
        logger.debug("📢 计算提及分数...")
        mentioned_score = self._calculate_mentioned_score(message, bot_nickname)
        logger.debug(f"📣 提及分数: {mentioned_score:.3f}")

        # 4. 计算总分
        logger.debug("🧮 计算加权总分...")
        total_score = (
            interest_match_score * self.score_weights["interest_match"] +
            relationship_score * self.score_weights["relationship"] +
            mentioned_score * self.score_weights["mentioned"]
        )

        details = {
            "interest_match": f"兴趣匹配度: {interest_match_score:.3f}",
            "relationship": f"关系分: {relationship_score:.3f}",
            "mentioned": f"提及分数: {mentioned_score:.3f}",
        }

        logger.info(f"📈 消息 {message.message_id} 最终评分: {total_score:.3f}")
        logger.debug(f"⚖️  评分权重: {self.score_weights}")
        logger.debug(f"📋 评分详情: {details}")

        return InterestScore(
            message_id=message.message_id,
            total_score=total_score,
            interest_match_score=interest_match_score,
            relationship_score=relationship_score,
            mentioned_score=mentioned_score,
            details=details
        )

    async def _calculate_interest_match_score(self, content: str, keywords: List[str] = None) -> float:
        """计算兴趣匹配度 - 使用智能embedding匹配"""
        if not content:
            return 0.0

        # 使用智能匹配（embedding）
        if self.use_smart_matching and bot_interest_manager.is_initialized:
            return await self._calculate_smart_interest_match(content, keywords)
        else:
            # 智能匹配未初始化，返回默认分数
            logger.warning("智能兴趣匹配系统未初始化，返回默认分数")
            return 0.3

    async def _calculate_smart_interest_match(self, content: str, keywords: List[str] = None) -> float:
        """使用embedding计算智能兴趣匹配"""
        try:
            logger.debug("🧠 开始智能兴趣匹配计算...")

            # 如果没有传入关键词，则提取
            if not keywords:
                logger.debug("🔍 从内容中提取关键词...")
                keywords = self._extract_keywords_from_content(content)
                logger.debug(f"🏷️  提取到 {len(keywords)} 个关键词")

            # 使用机器人兴趣管理器计算匹配度
            logger.debug("🤖 调用机器人兴趣管理器计算匹配度...")
            match_result = await bot_interest_manager.calculate_interest_match(content, keywords)

            if match_result:
                logger.debug("✅ 智能兴趣匹配成功:")
                logger.debug(f"   📊 总分: {match_result.overall_score:.3f}")
                logger.debug(f"   🏷️  匹配标签: {match_result.matched_tags}")
                logger.debug(f"   🎯 最佳标签: {match_result.top_tag}")
                logger.debug(f"   📈 置信度: {match_result.confidence:.3f}")
                logger.debug(f"   🔢 匹配详情: {match_result.match_scores}")

                # 返回匹配分数，考虑置信度和匹配标签数量
                match_count_bonus = min(len(match_result.matched_tags) * 0.05, 0.3)  # 每多匹配一个标签+0.05，最高+0.3
                final_score = match_result.overall_score * 1.3 * match_result.confidence + match_count_bonus
                logger.debug(f"⚖️  最终分数计算: 总分({match_result.overall_score:.3f}) × 1.3 × 置信度({match_result.confidence:.3f}) + 标签数量奖励({match_count_bonus:.3f}) = {final_score:.3f}")
                return final_score
            else:
                logger.warning("⚠️ 智能兴趣匹配未返回结果")
                return 0.0

        except Exception as e:
            logger.error(f"❌ 智能兴趣匹配计算失败: {e}")
            logger.debug("🔍 错误详情:")
            logger.debug(f"   💬 内容长度: {len(content)} 字符")
            logger.debug(f"   🏷️  关键词数量: {len(keywords) if keywords else 0}")
            return 0.0

    def _extract_keywords_from_database(self, message: DatabaseMessages) -> List[str]:
        """从数据库消息中提取关键词"""
        keywords = []

        # 尝试从 key_words 字段提取（存储的是JSON字符串）
        if message.key_words:
            try:
                import orjson
                keywords = orjson.loads(message.key_words)
                if not isinstance(keywords, list):
                    keywords = []
            except (orjson.JSONDecodeError, TypeError):
                keywords = []

        # 如果没有 keywords，尝试从 key_words_lite 提取
        if not keywords and message.key_words_lite:
            try:
                import orjson
                keywords = orjson.loads(message.key_words_lite)
                if not isinstance(keywords, list):
                    keywords = []
            except (orjson.JSONDecodeError, TypeError):
                keywords = []

        # 如果还是没有，从消息内容中提取（降级方案）
        if not keywords:
            keywords = self._extract_keywords_from_content(message.processed_plain_text)

        return keywords[:15]  # 返回前15个关键词

    def _extract_keywords_from_content(self, content: str) -> List[str]:
        """从内容中提取关键词（降级方案）"""
        import re

        # 清理文本
        content = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', content)  # 保留中文、英文、数字
        words = content.split()

        # 过滤和关键词提取
        keywords = []
        for word in words:
            word = word.strip()
            if (len(word) >= 2 and  # 至少2个字符
                word.isalnum() and  # 字母数字
                not word.isdigit()):  # 不是纯数字
                keywords.append(word.lower())

        # 去重并限制数量
        unique_keywords = list(set(keywords))
        return unique_keywords[:10]  # 返回前10个唯一关键词

    def _calculate_relationship_score(self, user_id: str) -> float:
        """计算关系分"""
        if user_id in self.user_relationships:
            relationship_value = self.user_relationships[user_id]
            return min(relationship_value, 1.0)
        return 0.3  # 默认新用户的基础分

    def _calculate_mentioned_score(self, msg: DatabaseMessages, bot_nickname: str) -> float:
        """计算提及分数"""
        if not msg.processed_plain_text:
            return 0.0

        if msg.is_mentioned or (bot_nickname and bot_nickname in msg.processed_plain_text):
            return 3.0
        
        return 0.0
    
    def should_reply(self, score: InterestScore) -> bool:
        """判断是否应该回复"""
        logger.info("🤔 评估是否应该回复...")
        logger.debug("📊 评分详情:")
        logger.debug(f"   📝 消息ID: {score.message_id}")
        logger.debug(f"   💯 总分: {score.total_score:.3f}")
        logger.debug(f"   🧠 兴趣匹配: {score.interest_match_score:.3f}")
        logger.debug(f"   🤝 关系分: {score.relationship_score:.3f}")
        logger.debug(f"   📢 提及分: {score.mentioned_score:.3f}")

        base_threshold = self.reply_threshold
        logger.debug(f"📋 基础阈值: {base_threshold:.3f}")

        # 如果被提及，降低阈值
        if score.mentioned_score >= 1.0:
            base_threshold = self.mention_threshold
            logger.debug(f"📣 消息提及了机器人，使用降低阈值: {base_threshold:.3f}")

        # 计算连续不回复的概率提升
        probability_boost = min(self.no_reply_count * self.probability_boost_per_no_reply, 0.8)
        effective_threshold = base_threshold - probability_boost

        logger.debug("📈 连续不回复统计:")
        logger.debug(f"   🚫 不回复次数: {self.no_reply_count}")
        logger.debug(f"   📈 概率提升: {probability_boost:.3f}")
        logger.debug(f"   🎯 有效阈值: {effective_threshold:.3f}")

        # 做出决策
        score.total_score = score.total_score * 1
        should_reply = score.total_score >= effective_threshold
        decision = "✅ 应该回复" if should_reply else "❌ 不回复"

        logger.info(f"🎯 回复决策: {decision}")
        logger.info(f"📊 决策依据: {score.total_score:.3f} {'>=' if should_reply else '<'} {effective_threshold:.3f}")

        return should_reply, score.total_score

    def record_reply_action(self, did_reply: bool):
        """记录回复动作"""
        old_count = self.no_reply_count

        if did_reply:
            self.no_reply_count = max(0, self.no_reply_count - 1)
            action = "✅ reply动作可用"
        else:
            self.no_reply_count += 1
            action = "❌ reply动作不可用"

        # 限制最大计数
        self.no_reply_count = min(self.no_reply_count, self.max_no_reply_count)

        logger.info(f"📊 记录回复动作: {action}")
        logger.info(f"📈 连续不回复次数: {old_count} → {self.no_reply_count}")
        logger.debug(f"📋 最大限制: {self.max_no_reply_count} 次")

    def update_user_relationship(self, user_id: str, relationship_change: float):
        """更新用户关系"""
        old_score = self.user_relationships.get(user_id, 0.3)  # 默认新用户分数
        new_score = max(0.0, min(1.0, old_score + relationship_change))

        self.user_relationships[user_id] = new_score

        change_direction = "📈" if relationship_change > 0 else "📉" if relationship_change < 0 else "➖"
        logger.info(f"{change_direction} 更新用户关系: {user_id}")
        logger.info(f"💝 关系分: {old_score:.3f} → {new_score:.3f} (变化: {relationship_change:+.3f})")
        logger.debug(f"👥 当前追踪用户数: {len(self.user_relationships)}")

    def get_user_relationship(self, user_id: str) -> float:
        """获取用户关系分"""
        return self.user_relationships.get(user_id, 0.3)

    def get_scoring_stats(self) -> Dict:
        """获取评分系统统计"""
        return {
            "no_reply_count": self.no_reply_count,
            "max_no_reply_count": self.max_no_reply_count,
            "reply_threshold": self.reply_threshold,
            "mention_threshold": self.mention_threshold,
            "user_relationships": len(self.user_relationships),
        }


    def reset_stats(self):
        """重置统计信息"""
        self.no_reply_count = 0
        logger.info("重置兴趣度评分系统统计")

    async def initialize_smart_interests(self, personality_description: str, personality_id: str = "default"):
        """初始化智能兴趣系统"""
        try:
            logger.info("🚀 开始初始化智能兴趣系统...")
            logger.info(f"📋 人设ID: {personality_id}")
            logger.info(f"📝 人设描述长度: {len(personality_description)} 字符")

            await bot_interest_manager.initialize(personality_description, personality_id)
            logger.info("✅ 智能兴趣系统初始化完成")

            # 显示初始化后的统计信息
            stats = bot_interest_manager.get_interest_stats()
            logger.info("📊 兴趣系统统计:")
            logger.info(f"   🏷️  总标签数: {stats.get('total_tags', 0)}")
            logger.info(f"   💾 缓存大小: {stats.get('cache_size', 0)}")
            logger.info(f"   🧠 模型: {stats.get('embedding_model', '未知')}")

        except Exception as e:
            logger.error(f"❌ 初始化智能兴趣系统失败: {e}")
            logger.error("🔍 错误详情:")
            traceback.print_exc()

    def get_matching_config(self) -> Dict[str, Any]:
        """获取匹配配置信息"""
        return {
            "use_smart_matching": self.use_smart_matching,
            "smart_system_initialized": bot_interest_manager.is_initialized,
            "smart_system_stats": bot_interest_manager.get_interest_stats() if bot_interest_manager.is_initialized else None
        }


# 创建全局兴趣评分系统实例
interest_scoring_system = InterestScoringSystem()
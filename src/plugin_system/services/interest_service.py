"""
兴趣系统服务
提供独立的兴趣管理功能，不依赖任何插件
"""


from src.chat.interest_system import bot_interest_manager
from src.common.logger import get_logger

logger = get_logger("interest_service")


class InterestService:
    """兴趣系统服务 - 独立于插件的兴趣管理"""

    def __init__(self):
        self.is_initialized = bot_interest_manager.is_initialized

    async def initialize_smart_interests(self, personality_description: str, personality_id: str = "default"):
        """
        初始化智能兴趣系统

        Args:
            personality_description: 机器人性格描述
            personality_id: 性格ID
        """
        try:
            logger.info("开始初始化智能兴趣系统...")
            logger.info(f"人设ID: {personality_id}, 描述长度: {len(personality_description)}")

            await bot_interest_manager.initialize(personality_description, personality_id)
            self.is_initialized = True
            logger.info("智能兴趣系统初始化完成。")

            # 显示初始化后的统计信息
            stats = bot_interest_manager.get_interest_stats()
            logger.info(f"兴趣系统统计: {stats}")

        except Exception as e:
            logger.error(f"初始化智能兴趣系统失败: {e}")
            self.is_initialized = False

    async def calculate_interest_match(
        self, content: str, keywords: list[str] | None = None, message_embedding: list[float] | None = None
    ):
        """
        计算消息与兴趣的匹配度

        Args:
            content: 消息内容
            keywords: 关键字列表
            message_embedding: 已经生成的消息embedding，可选

        Returns:
            匹配结果
        """
        if not self.is_initialized:
            logger.warning("兴趣系统未初始化，无法计算匹配度")
            return None

        try:
            if not keywords:
                # 如果没有关键字，则从内容中提取
                keywords = self._extract_keywords_from_content(content)

            return await bot_interest_manager.calculate_interest_match(content, keywords, message_embedding)
        except Exception as e:
            logger.error(f"计算兴趣匹配失败: {e}")
            return None

    def _extract_keywords_from_content(self, content: str) -> list[str]:
        """从内容中提取关键词"""
        import re

        # 清理文本
        content = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", content)  # 保留中文、英文、数字
        words = content.split()

        # 过滤和关键词提取
        keywords = []
        for word in words:
            word = word.strip()
            if (
                len(word) >= 2  # 至少2个字符
                and word.isalnum()  # 字母数字
                and not word.isdigit()
            ):  # 不是纯数字
                keywords.append(word.lower())

        # 去重并限制数量
        unique_keywords = list(set(keywords))
        return unique_keywords[:10]  # 返回前10个唯一关键词

    def get_interest_stats(self) -> dict:
        """获取兴趣系统统计信息"""
        if not self.is_initialized:
            return {"initialized": False}

        try:
            return {
                "initialized": True,
                **bot_interest_manager.get_interest_stats()
            }
        except Exception as e:
            logger.error(f"获取兴趣系统统计失败: {e}")
            return {"initialized": True, "error": str(e)}


# 创建全局实例
interest_service = InterestService()

# -*- coding: utf-8 -*-
"""
内容服务模块
负责生成所有与QQ空间相关的文本内容，例如说说、评论等。
"""
from typing import Callable
import datetime

from src.common.logger import get_logger
from src.plugin_system.apis import llm_api, config_api

# 导入旧的工具函数，我们稍后会考虑是否也需要重构它
from ..utils.history_utils import get_send_history

logger = get_logger("MaiZone.ContentService")


class ContentService:
    """
    内容服务类，封装了所有与大语言模型（LLM）交互以生成文本的逻辑。
    """

    def __init__(self, get_config: Callable):
        """
        初始化内容服务。

        :param get_config: 一个函数，用于从插件主类获取配置信息。
        """
        self.get_config = get_config

    async def generate_story(self, topic: str) -> str:
        """
        根据指定主题生成一条QQ空间说说。

        :param topic: 说说的主题。
        :return: 生成的说说内容，如果失败则返回空字符串。
        """
        try:
            # 获取模型配置
            models = llm_api.get_available_models()
            text_model = str(self.get_config("models.text_model", "replyer_1"))
            model_config = models.get(text_model)

            if not model_config:
                logger.error("未配置LLM模型")
                return ""

            # 获取机器人信息
            bot_personality = config_api.get_global_config("personality.personality_core", "一个机器人")
            bot_expression = config_api.get_global_config("personality.reply_style", "内容积极向上")
            qq_account = config_api.get_global_config("bot.qq_account", "")

            # 获取当前时间信息
            now = datetime.datetime.now()
            current_time = now.strftime("%Y年%m月%d日 %H:%M")
            weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            weekday = weekday_names[now.weekday()]

            # 构建提示词
            if topic:
                prompt = f"""
                你是'{bot_personality}'，现在是{current_time}（{weekday}），你想写一条主题是'{topic}'的说说发表在qq空间上，
                {bot_expression}
                不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，可以适当使用颜文字，
                你可以在说说中自然地提及当前的时间（如"今天"、"现在"、"此刻"等），让说说更贴近发布时间，
                只输出一条说说正文的内容，不要有其他的任何正文以外的冗余输出
                """
            else:
                prompt = f"""
                你是'{bot_personality}'，现在是{current_time}（{weekday}），你想写一条说说发表在qq空间上，主题不限
                {bot_expression}
                不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，可以适当使用颜文字，
                你可以在说说中自然地提及当前的时间（如"今天"、"现在"、"此刻"等），让说说更贴近发布时间，
                只输出一条说说正文的内容，不要有其他的任何正文以外的冗余输出
                """

            # 添加历史记录以避免重复
            prompt += "\n以下是你以前发过的说说，写新说说时注意不要在相隔不长的时间发送相同主题的说说"
            history_block = await get_send_history(qq_account)
            if history_block:
                prompt += history_block

            # 调用LLM生成内容
            success, story, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="story.generate",
                temperature=0.3,
                max_tokens=1000
            )

            if success:
                logger.info(f"成功生成说说内容：'{story}'")
                return story
            else:
                logger.error("生成说说内容失败")
                return ""

        except Exception as e:
            logger.error(f"生成说说内容时发生异常: {e}")
            return ""

    async def generate_comment(self, content: str, target_name: str, rt_con: str = "") -> str:
        """
        针对一条具体的说说内容生成评论。

        :param content: 好友的说说内容。
        :param target_name: 好友的昵称。
        :param rt_con: 如果是转发的说说，这里是原说说内容。
        :return: 生成的评论内容，如果失败则返回空字符串。
        """
        try:
            # 获取模型配置
            models = llm_api.get_available_models()
            text_model = str(self.get_config("models.text_model", "replyer_1"))
            model_config = models.get(text_model)

            if not model_config:
                logger.error("未配置LLM模型")
                return ""

            # 获取机器人信息
            bot_personality = config_api.get_global_config("personality.personality_core", "一个机器人")
            bot_expression = config_api.get_global_config("expression.expression_style", "内容积极向上")

            # 构建提示词
            if not rt_con:
                prompt = f"""
                你是'{bot_personality}'，你正在浏览你好友'{target_name}'的QQ空间，
                你看到了你的好友'{target_name}'qq空间上内容是'{content}'的说说，你想要发表你的一条评论，
                {bot_expression}，回复的平淡一些，简短一些，说中文，
                不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容
                """
            else:
                prompt = f"""
                你是'{bot_personality}'，你正在浏览你好友'{target_name}'的QQ空间，
                你看到了你的好友'{target_name}'在qq空间上转发了一条内容为'{rt_con}'的说说，你的好友的评论为'{content}'
                你想要发表你的一条评论，{bot_expression}，回复的平淡一些，简短一些，说中文，
                不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容
                """

            logger.info(f"正在为'{target_name}'的说说生成评论: {content[:20]}...")

            # 调用LLM生成评论
            success, comment, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="comment.generate",
                temperature=0.3,
                max_tokens=100
            )

            if success:
                logger.info(f"成功生成评论内容：'{comment}'")
                return comment
            else:
                logger.error("生成评论内容失败")
                return ""

        except Exception as e:
            logger.error(f"生成评论内容时发生异常: {e}")
            return ""

    async def generate_comment_reply(self, story_content: str, comment_content: str, commenter_name: str) -> str:
        """
        针对自己说说的评论，生成回复。

        :param story_content: 原始说说内容。
        :param comment_content: 好友的评论内容。
        :param commenter_name: 评论者的昵称。
        :return: 生成的回复内容。
        """
        try:
            models = llm_api.get_available_models()
            text_model = str(self.get_config("models.text_model", "replyer_1"))
            model_config = models.get(text_model)
            if not model_config:
                return ""

            bot_personality = config_api.get_global_config("personality.personality_core", "一个机器人")
            bot_expression = config_api.get_global_config("expression.expression_style", "内容积极向上")

            prompt = f"""
            你是'{bot_personality}'，你的好友'{commenter_name}'评论了你QQ空间上的一条内容为“{story_content}”说说，
            你的好友对该说说的评论为:“{comment_content}”，你想要对此评论进行回复
            {bot_expression}，回复的平淡一些，简短一些，说中文，
            不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容
            """
            
            success, reply, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="comment.reply.generate",
                temperature=0.3,
                max_tokens=100
            )

            if success:
                logger.info(f"成功为'{commenter_name}'的评论生成回复: '{reply}'")
                return reply
            else:
                logger.error("生成评论回复失败")
                return ""
        except Exception as e:
            logger.error(f"生成评论回复时发生异常: {e}")
            return ""

    async def generate_story_from_activity(self, activity: str) -> str:
        """
        根据当前的日程活动生成一条QQ空间说说。

        :param activity: 当前的日程活动名称。
        :return: 生成的说说内容，如果失败则返回空字符串。
        """
        try:
            # 获取模型配置
            models = llm_api.get_available_models()
            text_model = str(self.get_config("models.text_model", "replyer_1"))
            model_config = models.get(text_model)

            if not model_config:
                logger.error("未配置LLM模型")
                return ""

            # 获取机器人信息
            bot_personality = config_api.get_global_config("personality.personality_core", "一个机器人")
            bot_expression = config_api.get_global_config("expression.expression_style", "内容积极向上")
            qq_account = config_api.get_global_config("bot.qq_account", "")

            # 获取当前时间信息
            now = datetime.datetime.now()
            current_time = now.strftime("%Y年%m月%d日 %H:%M")
            weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            weekday = weekday_names[now.weekday()]

            # 构建基于活动的提示词
            prompt = f"""
            你是'{bot_personality}'，现在是{current_time}（{weekday}），根据你当前的日程安排，你正在'{activity}'。
            请基于这个活动写一条说说发表在qq空间上，
            {bot_expression}
            说说内容应该自然地反映你正在做的事情或你的想法，
            不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，可以适当使用颜文字，
            你可以在说说中自然地提及当前的时间（如"今天"、"现在"、"此刻"等），让说说更贴近发布时间，
            只输出一条说说正文的内容，不要有其他的任何正文以外的冗余输出
            
            注意：
            - 如果活动是学习相关的，可以分享学习心得或感受
            - 如果活动是休息相关的，可以分享放松的感受
            - 如果活动是日常生活相关的，可以分享生活感悟
            - 让说说内容贴近你当前正在做的事情，显得自然真实
            """

            # 添加历史记录避免重复
            prompt += "\n\n以下是你最近发过的说说，写新说说时注意不要在相隔不长的时间发送相似内容的说说\n"
            history_block = await get_send_history(qq_account)
            if history_block:
                prompt += history_block

            # 生成内容
            success, story, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="story.generate.activity",
                temperature=0.7,  # 稍微提高创造性
                max_tokens=1000
            )

            if success:
                logger.info(f"成功生成基于活动的说说内容：'{story}'")
                return story
            else:
                logger.error("生成基于活动的说说内容失败")
                return ""
                
        except Exception as e:
            logger.error(f"生成基于活动的说说内容异常: {e}")
            return ""
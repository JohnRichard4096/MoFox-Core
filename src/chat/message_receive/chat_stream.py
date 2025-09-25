import asyncio
import hashlib
import time
import copy
from typing import Dict, Optional, TYPE_CHECKING
from rich.traceback import install
from maim_message import GroupInfo, UserInfo

from src.common.logger import get_logger
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.mysql import insert as mysql_insert
from src.common.database.sqlalchemy_models import ChatStreams  # 新增导入
from src.common.database.sqlalchemy_database_api import get_db_session
from src.config.config import global_config  # 新增导入

# 避免循环导入，使用TYPE_CHECKING进行类型提示
if TYPE_CHECKING:
    from .message import MessageRecv


install(extra_lines=3)


logger = get_logger("chat_stream")


class ChatMessageContext:
    """聊天消息上下文，存储消息的上下文信息"""

    def __init__(self, message: "MessageRecv"):
        self.message = message

    def get_template_name(self) -> Optional[str]:
        """获取模板名称"""
        if self.message.message_info.template_info and not self.message.message_info.template_info.template_default:
            return self.message.message_info.template_info.template_name  # type: ignore
        return None

    def get_last_message(self) -> "MessageRecv":
        """获取最后一条消息"""
        return self.message

    def check_types(self, types: list) -> bool:
        # sourcery skip: invert-any-all, use-any, use-next
        """检查消息类型"""
        if not self.message.message_info.format_info.accept_format:  # type: ignore
            return False
        for t in types:
            if t not in self.message.message_info.format_info.accept_format:  # type: ignore
                return False
        return True

    def get_priority_mode(self) -> str:
        """获取优先级模式"""
        return self.message.priority_mode

    def get_priority_info(self) -> Optional[dict]:
        """获取优先级信息"""
        if hasattr(self.message, "priority_info") and self.message.priority_info:
            return self.message.priority_info
        return None


class ChatStream:
    """聊天流对象，存储一个完整的聊天上下文"""

    def __init__(
        self,
        stream_id: str,
        platform: str,
        user_info: UserInfo,
        group_info: Optional[GroupInfo] = None,
        data: Optional[dict] = None,
    ):
        self.stream_id = stream_id
        self.platform = platform
        self.user_info = user_info
        self.group_info = group_info
        self.create_time = data.get("create_time", time.time()) if data else time.time()
        self.last_active_time = data.get("last_active_time", self.create_time) if data else self.create_time
        self.energy_value = data.get("energy_value", 5.0) if data else 5.0
        self.sleep_pressure = data.get("sleep_pressure", 0.0) if data else 0.0
        self.saved = False
        self.context: ChatMessageContext = None  # type: ignore # 用于存储该聊天的上下文信息

        # 动态兴趣度系统 - 重构后的focus_energy
        self.base_interest_energy = data.get("base_interest_energy", 0.5) if data else 0.5
        self.message_interest_total = data.get("message_interest_total", 0.0) if data else 0.0
        self.message_count = data.get("message_count", 0) if data else 0
        self.action_count = data.get("action_count", 0) if data else 0
        self.reply_count = data.get("reply_count", 0) if data else 0
        self.last_interaction_time = data.get("last_interaction_time", time.time()) if data else time.time()
        self.consecutive_no_reply = data.get("consecutive_no_reply", 0) if data else 0

        # 计算动态focus_energy
        self.focus_energy = self._calculate_dynamic_focus_energy()
        self.no_reply_consecutive = 0
        self.breaking_accumulated_interest = 0.0

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "stream_id": self.stream_id,
            "platform": self.platform,
            "user_info": self.user_info.to_dict() if self.user_info else None,
            "group_info": self.group_info.to_dict() if self.group_info else None,
            "create_time": self.create_time,
            "last_active_time": self.last_active_time,
            "energy_value": self.energy_value,
            "sleep_pressure": self.sleep_pressure,
            "focus_energy": self.focus_energy,
            "breaking_accumulated_interest": self.breaking_accumulated_interest,
            # 新增动态兴趣度系统字段
            "base_interest_energy": self.base_interest_energy,
            "message_interest_total": self.message_interest_total,
            "message_count": self.message_count,
            "action_count": self.action_count,
            "reply_count": self.reply_count,
            "last_interaction_time": self.last_interaction_time,
            "consecutive_no_reply": self.consecutive_no_reply,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatStream":
        """从字典创建实例"""
        user_info = UserInfo.from_dict(data.get("user_info", {})) if data.get("user_info") else None
        group_info = GroupInfo.from_dict(data.get("group_info", {})) if data.get("group_info") else None

        return cls(
            stream_id=data["stream_id"],
            platform=data["platform"],
            user_info=user_info,  # type: ignore
            group_info=group_info,
            data=data,
        )

    def update_active_time(self):
        """更新最后活跃时间"""
        self.last_active_time = time.time()
        self.saved = False

    def set_context(self, message: "MessageRecv"):
        """设置聊天消息上下文"""
        self.context = ChatMessageContext(message)

    def _calculate_dynamic_focus_energy(self) -> float:
        """动态计算聊天流的总体兴趣度"""
        try:
            # 基础分：平均消息兴趣度
            avg_message_interest = self.message_interest_total / max(self.message_count, 1)

            # 动作参与度：动作执行率
            action_rate = self.action_count / max(self.message_count, 1)

            # 回复活跃度：回复率
            reply_rate = self.reply_count / max(self.message_count, 1)

            # 获取用户关系分（对于私聊，群聊无效）
            relationship_factor = self._get_user_relationship_score()

            # 时间衰减因子：最近活跃度
            current_time = time.time()
            if not self.last_interaction_time:
                self.last_interaction_time = current_time
            time_since_interaction = current_time - self.last_interaction_time
            time_decay = max(0.3, 1.0 - min(time_since_interaction / (7 * 24 * 3600), 0.7))  # 7天衰减

            # 连续无回复惩罚
            no_reply_penalty = max(0.1, 1.0 - self.consecutive_no_reply * 0.1)

            # 获取AFC系统阈值，添加None值检查
            reply_threshold = getattr(global_config.affinity_flow, 'reply_action_interest_threshold', 0.4)
            non_reply_threshold = getattr(global_config.affinity_flow, 'non_reply_action_interest_threshold', 0.2)
            high_match_threshold = getattr(global_config.affinity_flow, 'high_match_interest_threshold', 0.8)

            # 计算与不同阈值的差距比例
            reply_gap_ratio = max(0, (avg_message_interest - reply_threshold) / max(0.1, (1.0 - reply_threshold)))
            non_reply_gap_ratio = max(0, (avg_message_interest - non_reply_threshold) / max(0.1, (1.0 - non_reply_threshold)))
            high_match_gap_ratio = max(0, (avg_message_interest - high_match_threshold) / max(0.1, (1.0 - high_match_threshold)))

            # 基于阈值差距比例的基础分计算
            threshold_based_score = (
                reply_gap_ratio * 0.6 +      # 回复阈值差距权重60%
                non_reply_gap_ratio * 0.2 +  # 非回复阈值差距权重20%
                high_match_gap_ratio * 0.2   # 高匹配阈值差距权重20%
            )

            # 动态权重调整：根据平均兴趣度水平调整权重分配
            if avg_message_interest >= high_match_threshold:
                # 高兴趣度：更注重阈值差距
                threshold_weight = 0.7
                activity_weight = 0.2
                relationship_weight = 0.1
            elif avg_message_interest >= reply_threshold:
                # 中等兴趣度：平衡权重
                threshold_weight = 0.5
                activity_weight = 0.3
                relationship_weight = 0.2
            else:
                # 低兴趣度：更注重活跃度提升
                threshold_weight = 0.3
                activity_weight = 0.5
                relationship_weight = 0.2

            # 计算活跃度得分
            activity_score = (action_rate * 0.6 + reply_rate * 0.4)

            # 综合计算：基于阈值的动态加权
            focus_energy = (
                threshold_based_score * threshold_weight +  # 阈值差距基础分
                activity_score * activity_weight +            # 活跃度得分
                relationship_factor * relationship_weight +   # 关系得分
                self.base_interest_energy * 0.05             # 基础兴趣微调
            ) * time_decay * no_reply_penalty

            # 确保在合理范围内
            focus_energy = max(0.1, min(1.0, focus_energy))

            # 应用非线性变换增强区分度
            if focus_energy >= 0.7:
                # 高兴趣度区域：指数增强，更敏感
                focus_energy = 0.7 + (focus_energy - 0.7) ** 0.8
            elif focus_energy >= 0.4:
                # 中等兴趣度区域：线性保持
                pass
            else:
                # 低兴趣度区域：对数压缩，减少区分度
                focus_energy = 0.4 * (focus_energy / 0.4) ** 1.2

            return max(0.1, min(1.0, focus_energy))

        except Exception as e:
            logger.error(f"计算动态focus_energy失败: {e}")
            return self.base_interest_energy

    def _get_user_relationship_score(self) -> float:
        """从外部系统获取用户关系分"""
        try:
            # 尝试从兴趣评分系统获取用户关系分
            from src.plugins.built_in.affinity_flow_chatter.interest_scoring import (
                chatter_interest_scoring_system,
            )

            if self.user_info and hasattr(self.user_info, 'user_id'):
                return chatter_interest_scoring_system.get_user_relationship(str(self.user_info.user_id))
        except Exception:
            pass

        # 默认基础分
        return 0.3

    def add_message_interest(self, interest_score: float):
        """添加消息兴趣值并更新focus_energy"""
        self.message_interest_total += interest_score
        self.message_count += 1
        self.last_interaction_time = time.time()
        self.focus_energy = self._calculate_dynamic_focus_energy()

    def update_focus_energy(self):
        """手动触发更新focus_energy"""
        self.focus_energy = self._calculate_dynamic_focus_energy()

    def record_action(self, is_reply: bool = False):
        """记录动作执行"""
        self.action_count += 1
        if is_reply:
            self.reply_count += 1
            self.consecutive_no_reply = max(0, self.consecutive_no_reply - 1)
        self.last_interaction_time = time.time()
        self.focus_energy = self._calculate_dynamic_focus_energy()

    def record_no_reply(self):
        """记录无回复动作"""
        self.consecutive_no_reply += 1
        self.last_interaction_time = time.time()
        self.focus_energy = self._calculate_dynamic_focus_energy()

    def get_adjusted_focus_energy(self) -> float:
        """获取应用了afc调整的focus_energy"""
        try:
            from src.chat.message_manager.message_manager import message_manager
            if self.stream_id in message_manager.stream_contexts:
                context = message_manager.stream_contexts[self.stream_id]
                afc_adjustment = context.get_afc_threshold_adjustment()
                # 对动态计算的focus_energy应用AFC调整
                adjusted_energy = max(0.0, self.focus_energy - afc_adjustment)
                return adjusted_energy
        except Exception:
            pass
        return self.focus_energy


class ChatManager:
    """聊天管理器，管理所有聊天流"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.streams: Dict[str, ChatStream] = {}  # stream_id -> ChatStream
            self.last_messages: Dict[str, "MessageRecv"] = {}  # stream_id -> last_message
            # try:
            # with get_db_session() as session:
            #     db.connect(reuse_if_open=True)
            #     # 确保 ChatStreams 表存在
            #     session.execute(text("CREATE TABLE IF NOT EXISTS chat_streams (stream_id TEXT PRIMARY KEY, platform TEXT, create_time REAL, last_active_time REAL, user_platform TEXT, user_id TEXT, user_nickname TEXT, user_cardname TEXT, group_platform TEXT, group_id TEXT, group_name TEXT)"))
            #     await session.commit()
            # except Exception as e:
            #     logger.error(f"数据库连接或 ChatStreams 表创建失败: {e}")

            self._initialized = True
            # 在事件循环中启动初始化
            # asyncio.create_task(self._initialize())
            # # 启动自动保存任务
            # asyncio.create_task(self._auto_save_task())

    async def _initialize(self):
        """异步初始化"""
        try:
            await self.load_all_streams()
            logger.info(f"聊天管理器已启动，已加载 {len(self.streams)} 个聊天流")
        except Exception as e:
            logger.error(f"聊天管理器启动失败: {str(e)}")

    async def _auto_save_task(self):
        """定期自动保存所有聊天流"""
        while True:
            await asyncio.sleep(300)  # 每5分钟保存一次
            try:
                await self._save_all_streams()
                logger.info("聊天流自动保存完成")
            except Exception as e:
                logger.error(f"聊天流自动保存失败: {str(e)}")

    def register_message(self, message: "MessageRecv"):
        """注册消息到聊天流"""
        stream_id = self._generate_stream_id(
            message.message_info.platform,  # type: ignore
            message.message_info.user_info,
            message.message_info.group_info,
        )
        self.last_messages[stream_id] = message
        # logger.debug(f"注册消息到聊天流: {stream_id}")

    @staticmethod
    def _generate_stream_id(
        platform: str, user_info: Optional[UserInfo], group_info: Optional[GroupInfo] = None
    ) -> str:
        """生成聊天流唯一ID"""
        if not user_info and not group_info:
            raise ValueError("用户信息或群组信息必须提供")

        if group_info:
            # 组合关键信息
            components = [platform, str(group_info.group_id)]
        else:
            components = [platform, str(user_info.user_id), "private"]  # type: ignore

        # 使用MD5生成唯一ID
        key = "_".join(components)
        return hashlib.md5(key.encode()).hexdigest()

    @staticmethod
    def get_stream_id(platform: str, id: str, is_group: bool = True) -> str:
        """获取聊天流ID"""
        components = [platform, id] if is_group else [platform, id, "private"]
        key = "_".join(components)
        return hashlib.md5(key.encode()).hexdigest()

    async def get_or_create_stream(
        self, platform: str, user_info: UserInfo, group_info: Optional[GroupInfo] = None
    ) -> ChatStream:
        """获取或创建聊天流

        Args:
            platform: 平台标识
            user_info: 用户信息
            group_info: 群组信息（可选）

        Returns:
            ChatStream: 聊天流对象
        """
        # 生成stream_id
        try:
            stream_id = self._generate_stream_id(platform, user_info, group_info)

            # 检查内存中是否存在
            if stream_id in self.streams:
                stream = self.streams[stream_id]

                # 更新用户信息和群组信息
                stream.update_active_time()
                stream = copy.deepcopy(stream)  # 返回副本以避免外部修改影响缓存
                if user_info and user_info.platform and user_info.user_id:
                    stream.user_info = user_info
                if group_info:
                    stream.group_info = group_info
                from .message import MessageRecv  # 延迟导入，避免循环引用

                if stream_id in self.last_messages and isinstance(self.last_messages[stream_id], MessageRecv):
                    stream.set_context(self.last_messages[stream_id])
                else:
                    logger.error(f"聊天流 {stream_id} 不在最后消息列表中，可能是新创建的")
                return stream

            # 检查数据库中是否存在
            async def _db_find_stream_async(s_id: str):
                async with get_db_session() as session:
                    return (await session.execute(select(ChatStreams).where(ChatStreams.stream_id == s_id))).scalars().first()

            model_instance = await _db_find_stream_async(stream_id)

            if model_instance:
                # 从 SQLAlchemy 模型转换回 ChatStream.from_dict 期望的格式
                user_info_data = {
                    "platform": model_instance.user_platform,
                    "user_id": model_instance.user_id,
                    "user_nickname": model_instance.user_nickname,
                    "user_cardname": model_instance.user_cardname or "",
                }
                group_info_data = None
                if model_instance and getattr(model_instance, "group_id", None):
                    group_info_data = {
                        "platform": model_instance.group_platform,
                        "group_id": model_instance.group_id,
                        "group_name": model_instance.group_name,
                    }

                data_for_from_dict = {
                    "stream_id": model_instance.stream_id,
                    "platform": model_instance.platform,
                    "user_info": user_info_data,
                    "group_info": group_info_data,
                    "create_time": model_instance.create_time,
                    "last_active_time": model_instance.last_active_time,
                    "energy_value": model_instance.energy_value,
                    "sleep_pressure": model_instance.sleep_pressure,
                }
                stream = ChatStream.from_dict(data_for_from_dict)
                # 更新用户信息和群组信息
                stream.user_info = user_info
                if group_info:
                    stream.group_info = group_info
                stream.update_active_time()
            else:
                # 创建新的聊天流
                stream = ChatStream(
                    stream_id=stream_id,
                    platform=platform,
                    user_info=user_info,
                    group_info=group_info,
                )
        except Exception as e:
            logger.error(f"获取或创建聊天流失败: {e}", exc_info=True)
            raise e

        stream = copy.deepcopy(stream)
        from .message import MessageRecv  # 延迟导入，避免循环引用

        if stream_id in self.last_messages and isinstance(self.last_messages[stream_id], MessageRecv):
            stream.set_context(self.last_messages[stream_id])
        else:
            logger.error(f"聊天流 {stream_id} 不在最后消息列表中，可能是新创建的")
        # 保存到内存和数据库
        self.streams[stream_id] = stream
        await self._save_stream(stream)
        return stream

    def get_stream(self, stream_id: str) -> Optional[ChatStream]:
        """通过stream_id获取聊天流"""
        stream = self.streams.get(stream_id)
        if not stream:
            return None
        if stream_id in self.last_messages:
            stream.set_context(self.last_messages[stream_id])
        return stream

    def get_stream_by_info(
        self, platform: str, user_info: UserInfo, group_info: Optional[GroupInfo] = None
    ) -> Optional[ChatStream]:
        """通过信息获取聊天流"""
        stream_id = self._generate_stream_id(platform, user_info, group_info)
        return self.streams.get(stream_id)

    def get_stream_name(self, stream_id: str) -> Optional[str]:
        """根据 stream_id 获取聊天流名称"""
        stream = self.get_stream(stream_id)
        if not stream:
            return None

        if stream.group_info and stream.group_info.group_name:
            return stream.group_info.group_name
        elif stream.user_info and stream.user_info.user_nickname:
            return f"{stream.user_info.user_nickname}的私聊"
        else:
            return None

    @staticmethod
    async def _save_stream(stream: ChatStream):
        """保存聊天流到数据库"""
        if stream.saved:
            return
        stream_data_dict = stream.to_dict()

        async def _db_save_stream_async(s_data_dict: dict):
            async with get_db_session() as session:
                user_info_d = s_data_dict.get("user_info")
                group_info_d = s_data_dict.get("group_info")
                fields_to_save = {
                    "platform": s_data_dict["platform"],
                    "create_time": s_data_dict["create_time"],
                    "last_active_time": s_data_dict["last_active_time"],
                    "user_platform": user_info_d["platform"] if user_info_d else "",
                    "user_id": user_info_d["user_id"] if user_info_d else "",
                    "user_nickname": user_info_d["user_nickname"] if user_info_d else "",
                    "user_cardname": user_info_d.get("user_cardname", "") if user_info_d else None,
                    "group_platform": group_info_d["platform"] if group_info_d else "",
                    "group_id": group_info_d["group_id"] if group_info_d else "",
                    "group_name": group_info_d["group_name"] if group_info_d else "",
                    "energy_value": s_data_dict.get("energy_value", 5.0),
                    "sleep_pressure": s_data_dict.get("sleep_pressure", 0.0),
                    "focus_energy": s_data_dict.get("focus_energy", 0.5),
                    # 新增动态兴趣度系统字段
                    "base_interest_energy": s_data_dict.get("base_interest_energy", 0.5),
                    "message_interest_total": s_data_dict.get("message_interest_total", 0.0),
                    "message_count": s_data_dict.get("message_count", 0),
                    "action_count": s_data_dict.get("action_count", 0),
                    "reply_count": s_data_dict.get("reply_count", 0),
                    "last_interaction_time": s_data_dict.get("last_interaction_time", time.time()),
                    "consecutive_no_reply": s_data_dict.get("consecutive_no_reply", 0),
                }
                if global_config.database.database_type == "sqlite":
                    stmt = sqlite_insert(ChatStreams).values(stream_id=s_data_dict["stream_id"], **fields_to_save)
                    stmt = stmt.on_conflict_do_update(index_elements=["stream_id"], set_=fields_to_save)
                elif global_config.database.database_type == "mysql":
                    stmt = mysql_insert(ChatStreams).values(stream_id=s_data_dict["stream_id"], **fields_to_save)
                    stmt = stmt.on_duplicate_key_update(
                        **{key: value for key, value in fields_to_save.items() if key != "stream_id"}
                    )
                else:
                    stmt = sqlite_insert(ChatStreams).values(stream_id=s_data_dict["stream_id"], **fields_to_save)
                    stmt = stmt.on_conflict_do_update(index_elements=["stream_id"], set_=fields_to_save)
                await session.execute(stmt)
                await session.commit()

        try:
            await _db_save_stream_async(stream_data_dict)
            stream.saved = True
        except Exception as e:
            logger.error(f"保存聊天流 {stream.stream_id} 到数据库失败 (SQLAlchemy): {e}", exc_info=True)

    async def _save_all_streams(self):
        """保存所有聊天流"""
        for stream in self.streams.values():
            await self._save_stream(stream)

    async def load_all_streams(self):
        """从数据库加载所有聊天流"""
        logger.info("正在从数据库加载所有聊天流")

        async def _db_load_all_streams_async():
            loaded_streams_data = []
            async with get_db_session() as session:
                for model_instance in (await session.execute(select(ChatStreams))).scalars().all():
                    user_info_data = {
                        "platform": model_instance.user_platform,
                        "user_id": model_instance.user_id,
                        "user_nickname": model_instance.user_nickname,
                        "user_cardname": model_instance.user_cardname or "",
                    }
                    group_info_data = None
                    if model_instance and getattr(model_instance, "group_id", None):
                        group_info_data = {
                            "platform": model_instance.group_platform,
                            "group_id": model_instance.group_id,
                            "group_name": model_instance.group_name,
                        }
                    data_for_from_dict = {
                        "stream_id": model_instance.stream_id,
                        "platform": model_instance.platform,
                        "user_info": user_info_data,
                        "group_info": group_info_data,
                        "create_time": model_instance.create_time,
                        "last_active_time": model_instance.last_active_time,
                        "energy_value": model_instance.energy_value,
                        "sleep_pressure": model_instance.sleep_pressure,
                        "focus_energy": getattr(model_instance, "focus_energy", 0.5),
                        # 新增动态兴趣度系统字段 - 使用getattr提供默认值
                        "base_interest_energy": getattr(model_instance, "base_interest_energy", 0.5),
                        "message_interest_total": getattr(model_instance, "message_interest_total", 0.0),
                        "message_count": getattr(model_instance, "message_count", 0),
                        "action_count": getattr(model_instance, "action_count", 0),
                        "reply_count": getattr(model_instance, "reply_count", 0),
                        "last_interaction_time": getattr(model_instance, "last_interaction_time", time.time()),
                        "relationship_score": getattr(model_instance, "relationship_score", 0.3),
                        "consecutive_no_reply": getattr(model_instance, "consecutive_no_reply", 0),
                    }
                    loaded_streams_data.append(data_for_from_dict)
                await session.commit()
            return loaded_streams_data

        try:
            all_streams_data_list = await _db_load_all_streams_async()
            self.streams.clear()
            for data in all_streams_data_list:
                stream = ChatStream.from_dict(data)
                stream.saved = True
                self.streams[stream.stream_id] = stream
                if stream.stream_id in self.last_messages:
                    stream.set_context(self.last_messages[stream.stream_id])
        except Exception as e:
            logger.error(f"从数据库加载所有聊天流失败 (SQLAlchemy): {e}", exc_info=True)


chat_manager = None


def get_chat_manager():
    global chat_manager
    if chat_manager is None:
        chat_manager = ChatManager()
    return chat_manager

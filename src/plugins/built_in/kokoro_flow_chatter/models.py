"""
Kokoro Flow Chatter 数据模型

定义心流聊天器的核心数据结构，包括：
- SessionStatus: 会话状态枚举
- EmotionalState: 情感状态模型
- MentalLogEntry: 心理活动日志条目
- KokoroSession: 完整的会话模型
- LLMResponseModel: LLM响应结构
- ActionModel: 动作模型
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import time


class SessionStatus(Enum):
    """
    会话状态枚举
    
    状态机核心，定义了KFC系统的四个基本状态：
    - IDLE: 空闲态，会话的起点和终点
    - RESPONDING: 响应中，正在处理消息和生成决策
    - WAITING: 等待态，已发送回复，等待用户回应
    - FOLLOW_UP_PENDING: 决策态，等待超时后进行后续决策
    """
    IDLE = "idle"
    RESPONDING = "responding"
    WAITING = "waiting"
    FOLLOW_UP_PENDING = "follow_up_pending"
    
    def __str__(self) -> str:
        return self.value


class MentalLogEventType(Enum):
    """
    心理活动日志事件类型
    
    用于标记线性叙事历史中不同类型的事件
    """
    USER_MESSAGE = "user_message"          # 用户消息事件
    BOT_ACTION = "bot_action"              # Bot行动事件
    WAITING_UPDATE = "waiting_update"      # 等待期间的心理更新
    TIMEOUT_DECISION = "timeout_decision"  # 超时决策事件
    STATE_CHANGE = "state_change"          # 状态变更事件
    CONTINUOUS_THINKING = "continuous_thinking"  # 连续思考事件
    PROACTIVE_THINKING = "proactive_thinking"    # 主动思考事件（长期沉默后主动发起）
    
    def __str__(self) -> str:
        return self.value


@dataclass
class EmotionalState:
    """
    动态情感状态模型
    
    记录和跟踪AI的情感参数，用于驱动个性化的交互行为
    
    Attributes:
        mood: 当前心情标签（如：开心、好奇、疲惫、沮丧）
        mood_intensity: 心情强度，0.0-1.0
        relationship_warmth: 关系热度，代表与用户的亲密度，0.0-1.0
        impression_of_user: 对用户的动态印象描述
        anxiety_level: 焦虑程度，0.0-1.0，在等待时会变化
        engagement_level: 投入程度，0.0-1.0，表示对当前对话的关注度
        last_update_time: 最后更新时间戳
    """
    mood: str = "neutral"
    mood_intensity: float = 0.5
    relationship_warmth: float = 0.5
    impression_of_user: str = ""
    anxiety_level: float = 0.0
    engagement_level: float = 0.5
    last_update_time: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "mood": self.mood,
            "mood_intensity": self.mood_intensity,
            "relationship_warmth": self.relationship_warmth,
            "impression_of_user": self.impression_of_user,
            "anxiety_level": self.anxiety_level,
            "engagement_level": self.engagement_level,
            "last_update_time": self.last_update_time,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmotionalState":
        """从字典创建实例"""
        return cls(
            mood=data.get("mood", "neutral"),
            mood_intensity=data.get("mood_intensity", 0.5),
            relationship_warmth=data.get("relationship_warmth", 0.5),
            impression_of_user=data.get("impression_of_user", ""),
            anxiety_level=data.get("anxiety_level", 0.0),
            engagement_level=data.get("engagement_level", 0.5),
            last_update_time=data.get("last_update_time", time.time()),
        )
    
    def update_anxiety_over_time(self, elapsed_seconds: float, max_wait_seconds: float) -> None:
        """
        根据等待时间更新焦虑程度
        
        Args:
            elapsed_seconds: 已等待的秒数
            max_wait_seconds: 最大等待秒数
        """
        if max_wait_seconds <= 0:
            return
        
        # 焦虑程度随时间流逝增加，使用平方根函数使增长趋于平缓
        wait_ratio = min(elapsed_seconds / max_wait_seconds, 1.0)
        self.anxiety_level = min(wait_ratio ** 0.5, 1.0)
        self.last_update_time = time.time()


@dataclass
class MentalLogEntry:
    """
    心理活动日志条目
    
    记录线性叙事历史中的每一个事件节点，
    是实现"连续主观体验"的核心数据结构
    
    Attributes:
        event_type: 事件类型
        timestamp: 事件发生时间戳
        thought: 内心独白
        content: 事件内容（如用户消息、Bot回复等）
        emotional_snapshot: 事件发生时的情感状态快照
        metadata: 额外元数据
    """
    event_type: MentalLogEventType
    timestamp: float
    thought: str = ""
    content: str = ""
    emotional_snapshot: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "event_type": str(self.event_type),
            "timestamp": self.timestamp,
            "thought": self.thought,
            "content": self.content,
            "emotional_snapshot": self.emotional_snapshot,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MentalLogEntry":
        """从字典创建实例"""
        event_type_str = data.get("event_type", "state_change")
        try:
            event_type = MentalLogEventType(event_type_str)
        except ValueError:
            event_type = MentalLogEventType.STATE_CHANGE
            
        return cls(
            event_type=event_type,
            timestamp=data.get("timestamp", time.time()),
            thought=data.get("thought", ""),
            content=data.get("content", ""),
            emotional_snapshot=data.get("emotional_snapshot"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class KokoroSession:
    """
    Kokoro Flow Chatter 会话模型
    
    为每个私聊用户维护一个独立的会话，包含：
    - 基本会话信息
    - 当前状态
    - 情感状态
    - 线性叙事历史（心理活动日志）
    - 等待相关的状态
    
    Attributes:
        user_id: 用户唯一标识
        stream_id: 聊天流ID
        status: 当前会话状态
        emotional_state: 动态情感状态
        mental_log: 线性叙事历史
        expected_user_reaction: 对用户回应的预期
        max_wait_seconds: 最大等待秒数
        waiting_since: 开始等待的时间戳
        last_bot_message: 最后一条Bot消息
        last_user_message: 最后一条用户消息
        created_at: 会话创建时间
        last_activity_at: 最后活动时间
        total_interactions: 总交互次数
    """
    user_id: str
    stream_id: str
    status: SessionStatus = SessionStatus.IDLE
    emotional_state: EmotionalState = field(default_factory=EmotionalState)
    mental_log: list[MentalLogEntry] = field(default_factory=list)
    
    # 等待状态相关
    expected_user_reaction: str = ""
    max_wait_seconds: int = 300
    waiting_since: Optional[float] = None
    
    # 消息记录
    last_bot_message: str = ""
    last_user_message: str = ""
    
    # 统计信息
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    total_interactions: int = 0
    
    # 连续思考相关
    continuous_thinking_count: int = 0
    last_continuous_thinking_at: Optional[float] = None
    
    # 主动思考相关（长期沉默后主动发起对话）
    last_proactive_at: Optional[float] = None  # 上次主动思考的时间
    proactive_count: int = 0  # 主动思考的次数（累计）
    
    def add_mental_log_entry(self, entry: MentalLogEntry, max_log_size: int = 100) -> None:
        """
        添加心理活动日志条目
        
        Args:
            entry: 日志条目
            max_log_size: 日志最大保留条数
        """
        self.mental_log.append(entry)
        self.last_activity_at = time.time()
        
        # 保持日志在合理大小
        if len(self.mental_log) > max_log_size:
            # 保留最近的日志
            self.mental_log = self.mental_log[-max_log_size:]
    
    def get_recent_mental_log(self, limit: int = 20) -> list[MentalLogEntry]:
        """获取最近的心理活动日志"""
        return self.mental_log[-limit:] if self.mental_log else []
    
    def get_waiting_duration(self) -> float:
        """获取当前等待时长（秒）"""
        if self.waiting_since is None:
            return 0.0
        return time.time() - self.waiting_since
    
    def is_wait_timeout(self) -> bool:
        """检查是否等待超时"""
        return self.get_waiting_duration() >= self.max_wait_seconds
    
    def start_waiting(self, expected_reaction: str, max_wait: int) -> None:
        """开始等待状态"""
        self.status = SessionStatus.WAITING
        self.expected_user_reaction = expected_reaction
        self.max_wait_seconds = max_wait
        self.waiting_since = time.time()
        self.continuous_thinking_count = 0
    
    def end_waiting(self) -> None:
        """结束等待状态"""
        self.waiting_since = None
        self.expected_user_reaction = ""
        self.continuous_thinking_count = 0
    
    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典格式"""
        return {
            "user_id": self.user_id,
            "stream_id": self.stream_id,
            "status": str(self.status),
            "emotional_state": self.emotional_state.to_dict(),
            "mental_log": [entry.to_dict() for entry in self.mental_log],
            "expected_user_reaction": self.expected_user_reaction,
            "max_wait_seconds": self.max_wait_seconds,
            "waiting_since": self.waiting_since,
            "last_bot_message": self.last_bot_message,
            "last_user_message": self.last_user_message,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "total_interactions": self.total_interactions,
            "continuous_thinking_count": self.continuous_thinking_count,
            "last_continuous_thinking_at": self.last_continuous_thinking_at,
            "last_proactive_at": self.last_proactive_at,
            "proactive_count": self.proactive_count,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KokoroSession":
        """从字典创建会话实例"""
        status_str = data.get("status", "idle")
        try:
            status = SessionStatus(status_str)
        except ValueError:
            status = SessionStatus.IDLE
        
        emotional_state = EmotionalState.from_dict(
            data.get("emotional_state", {})
        )
        
        mental_log = [
            MentalLogEntry.from_dict(entry) 
            for entry in data.get("mental_log", [])
        ]
        
        return cls(
            user_id=data.get("user_id", ""),
            stream_id=data.get("stream_id", ""),
            status=status,
            emotional_state=emotional_state,
            mental_log=mental_log,
            expected_user_reaction=data.get("expected_user_reaction", ""),
            max_wait_seconds=data.get("max_wait_seconds", 300),
            waiting_since=data.get("waiting_since"),
            last_bot_message=data.get("last_bot_message", ""),
            last_user_message=data.get("last_user_message", ""),
            created_at=data.get("created_at", time.time()),
            last_activity_at=data.get("last_activity_at", time.time()),
            total_interactions=data.get("total_interactions", 0),
            continuous_thinking_count=data.get("continuous_thinking_count", 0),
            last_continuous_thinking_at=data.get("last_continuous_thinking_at"),
            last_proactive_at=data.get("last_proactive_at"),
            proactive_count=data.get("proactive_count", 0),
        )


@dataclass
class ActionModel:
    """
    动作模型
    
    表示LLM决策的单个动作
    
    Attributes:
        type: 动作类型（reply, poke_user, send_reaction, update_internal_state, do_nothing）
        params: 动作参数
    """
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "type": self.type,
            **self.params
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionModel":
        """从字典创建实例"""
        action_type = data.get("type", "do_nothing")
        params = {k: v for k, v in data.items() if k != "type"}
        return cls(type=action_type, params=params)


@dataclass
class LLMResponseModel:
    """
    LLM响应模型
    
    定义LLM输出的结构化JSON格式
    
    Attributes:
        thought: 内心独白（必须）
        expected_user_reaction: 用户回应预期（必须）
        max_wait_seconds: 最长等待秒数（必须）
        actions: 行动列表（必须）
        plan: 行动意图（可选）
        emotional_updates: 情感状态更新（可选）
    """
    thought: str
    expected_user_reaction: str
    max_wait_seconds: int
    actions: list[ActionModel]
    plan: str = ""
    emotional_updates: Optional[dict[str, Any]] = None
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        result = {
            "thought": self.thought,
            "expected_user_reaction": self.expected_user_reaction,
            "max_wait_seconds": self.max_wait_seconds,
            "actions": [action.to_dict() for action in self.actions],
        }
        if self.plan:
            result["plan"] = self.plan
        if self.emotional_updates:
            result["emotional_updates"] = self.emotional_updates
        return result
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMResponseModel":
        """从字典创建实例"""
        actions = [
            ActionModel.from_dict(action) 
            for action in data.get("actions", [])
        ]
        
        # 如果没有actions，添加默认的do_nothing
        if not actions:
            actions = [ActionModel(type="do_nothing")]
        
        return cls(
            thought=data.get("thought", ""),
            expected_user_reaction=data.get("expected_user_reaction", ""),
            max_wait_seconds=data.get("max_wait_seconds", 300),
            actions=actions,
            plan=data.get("plan", ""),
            emotional_updates=data.get("emotional_updates"),
        )
    
    @classmethod
    def create_error_response(cls, error_message: str) -> "LLMResponseModel":
        """创建错误响应"""
        return cls(
            thought=f"出现了问题：{error_message}",
            expected_user_reaction="用户可能会感到困惑",
            max_wait_seconds=60,
            actions=[ActionModel(type="do_nothing")],
        )


@dataclass
class ContinuousThinkingResult:
    """
    连续思考结果
    
    在等待期间触发的心理活动更新结果
    """
    thought: str
    anxiety_level: float
    should_follow_up: bool = False
    follow_up_message: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "thought": self.thought,
            "anxiety_level": self.anxiety_level,
            "should_follow_up": self.should_follow_up,
            "follow_up_message": self.follow_up_message,
        }

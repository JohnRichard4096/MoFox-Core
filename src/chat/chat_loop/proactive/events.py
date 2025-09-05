from dataclasses import dataclass, field
from typing import Optional, Dict, Any

@dataclass
class ProactiveTriggerEvent:
    """
    主动思考触发事件的数据类
    """
    source: str  # 触发源的标识，例如 "silence_monitor", "insomnia_manager"
    reason: str  # 触发的具体原因，例如 "聊天已沉默10分钟", "深夜emo"
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)  # 可选的元数据，用于传递额外信息
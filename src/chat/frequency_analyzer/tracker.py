import orjson
import time
from typing import Dict, List, Optional
from pathlib import Path

from src.common.logger import get_logger

# 数据存储路径
DATA_DIR = Path("data/frequency_analyzer")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRACKER_FILE = DATA_DIR / "chat_timestamps.json"

logger = get_logger("ChatFrequencyTracker")


class ChatFrequencyTracker:
    """
    负责跟踪和存储用户聊天启动时间戳。
    """

    def __init__(self):
        self._timestamps: Dict[str, List[float]] = self._load_timestamps()

    def _load_timestamps(self) -> Dict[str, List[float]]:
        """从本地文件加载时间戳数据。"""
        if not TRACKER_FILE.exists():
            return {}
        try:
            with open(TRACKER_FILE, "rb") as f:
                data = orjson.loads(f.read())
            logger.info(f"成功从 {TRACKER_FILE} 加载了聊天时间戳数据。")
            return data
        except orjson.JSONDecodeError:
            logger.warning(f"无法解析 {TRACKER_FILE}，将创建一个新的空数据文件。")
            return {}
        except Exception as e:
            logger.error(f"加载聊天时间戳数据时发生未知错误: {e}")
            return {}

    def _save_timestamps(self):
        """将当前的时间戳数据保存到本地文件。"""
        try:
            with open(TRACKER_FILE, "wb") as f:
                f.write(orjson.dumps(self._timestamps))
        except Exception as e:
            logger.error(f"保存聊天时间戳数据到 {TRACKER_FILE} 时失败: {e}")

    def record_chat_start(self, chat_id: str):
        """
        记录一次聊天会话的开始。

        Args:
            chat_id (str): 唯一的聊天标识符 (例如，用户ID)。
        """
        now = time.time()
        if chat_id not in self._timestamps:
            self._timestamps[chat_id] = []
        
        self._timestamps[chat_id].append(now)
        logger.debug(f"为 chat_id '{chat_id}' 记录了新的聊天时间: {now}")
        self._save_timestamps()

    def get_timestamps_for_chat(self, chat_id: str) -> Optional[List[float]]:
        """
        获取指定聊天的所有时间戳记录。

        Args:
            chat_id (str): 聊天标识符。

        Returns:
            Optional[List[float]]: 时间戳列表，如果不存在则返回 None。
        """
        return self._timestamps.get(chat_id)


# 创建一个全局单例
chat_frequency_tracker = ChatFrequencyTracker()

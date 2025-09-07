"""
Chat Frequency Analyzer
=======================

本模块负责分析用户的聊天时间戳，以识别出他们最活跃的聊天时段（高峰时段）。

核心功能:
- 使用滑动窗口算法来检测时间戳集中的区域。
- 提供接口查询指定用户当前是否处于其聊天高峰时段内。
- 结果会被缓存以提高性能。

可配置参数:
- ANALYSIS_WINDOW_HOURS: 用于分析的时间窗口大小（小时）。
- MIN_CHATS_FOR_PEAK: 在一个窗口内需要多少次聊天才能被认为是高峰时段。
- MIN_GAP_BETWEEN_PEAKS_HOURS: 两个独立高峰时段之间的最小间隔（小时）。
"""
import time as time_module
from datetime import datetime, timedelta, time
from typing import List, Tuple, Optional

from .tracker import chat_frequency_tracker

# --- 可配置参数 ---
# 用于分析的时间窗口大小（小时）
ANALYSIS_WINDOW_HOURS = 2
# 触发高峰时段所需的最小聊天次数
MIN_CHATS_FOR_PEAK = 4
# 两个独立高峰时段之间的最小间隔（小时）
MIN_GAP_BETWEEN_PEAKS_HOURS = 1


class ChatFrequencyAnalyzer:
    """
    分析聊天时间戳，以识别用户的高频聊天时段。
    """

    def __init__(self):
        # 缓存分析结果，避免重复计算
        # 格式: { "chat_id": (timestamp_of_analysis, [peak_windows]) }
        self._analysis_cache: dict[str, tuple[float, list[tuple[time, time]]]] = {}
        self._cache_ttl_seconds = 60 * 30  # 缓存30分钟

    def _find_peak_windows(self, timestamps: List[float]) -> List[Tuple[datetime, datetime]]:
        """
        使用滑动窗口算法来识别时间戳列表中的高峰时段。

        Args:
            timestamps (List[float]): 按时间排序的聊天时间戳。

        Returns:
            List[Tuple[datetime, datetime]]: 识别出的高峰时段列表，每个元组代表一个时间窗口的开始和结束。
        """
        if len(timestamps) < MIN_CHATS_FOR_PEAK:
            return []

        # 将时间戳转换为 datetime 对象
        datetimes = [datetime.fromtimestamp(ts) for ts in timestamps]
        datetimes.sort()

        peak_windows: List[Tuple[datetime, datetime]] = []
        window_start_idx = 0

        for i in range(len(datetimes)):
            # 移动窗口的起始点
            while datetimes[i] - datetimes[window_start_idx] > timedelta(hours=ANALYSIS_WINDOW_HOURS):
                window_start_idx += 1

            # 检查当前窗口是否满足高峰条件
            if i - window_start_idx + 1 >= MIN_CHATS_FOR_PEAK:
                current_window_start = datetimes[window_start_idx]
                current_window_end = datetimes[i]

                # 合并重叠或相邻的高峰时段
                if peak_windows and current_window_start - peak_windows[-1][1] < timedelta(hours=MIN_GAP_BETWEEN_PEAKS_HOURS):
                    # 扩展上一个窗口的结束时间
                    peak_windows[-1] = (peak_windows[-1][0], current_window_end)
                else:
                    peak_windows.append((current_window_start, current_window_end))
        
        return peak_windows

    def get_peak_chat_times(self, chat_id: str) -> List[Tuple[time, time]]:
        """
        获取指定用户的高峰聊天时间段。

        Args:
            chat_id (str): 聊天标识符。

        Returns:
            List[Tuple[time, time]]: 高峰时段的列表，每个元组包含开始和结束时间 (time 对象)。
        """
        # 检查缓存
        cached_timestamp, cached_windows = self._analysis_cache.get(chat_id, (0, []))
        if time_module.time() - cached_timestamp < self._cache_ttl_seconds:
            return cached_windows

        timestamps = chat_frequency_tracker.get_timestamps_for_chat(chat_id)
        if not timestamps:
            return []

        peak_datetime_windows = self._find_peak_windows(timestamps)
        
        # 将 datetime 窗口转换为 time 窗口，并进行归一化处理
        peak_time_windows = []
        for start_dt, end_dt in peak_datetime_windows:
            # TODO:这里可以添加更复杂的逻辑来处理跨天的平均时间
            # 为简化，我们直接使用窗口的起止时间
            peak_time_windows.append((start_dt.time(), end_dt.time()))

        # 更新缓存
        self._analysis_cache[chat_id] = (time_module.time(), peak_time_windows)
        
        return peak_time_windows

    def is_in_peak_time(self, chat_id: str, now: Optional[datetime] = None) -> bool:
        """
        检查当前时间是否处于用户的高峰聊天时段内。

        Args:
            chat_id (str): 聊天标识符。
            now (Optional[datetime]): 要检查的时间，默认为当前时间。

        Returns:
            bool: 如果处于高峰时段则返回 True，否则返回 False。
        """
        if now is None:
            now = datetime.now()
        
        now_time = now.time()
        peak_times = self.get_peak_chat_times(chat_id)

        for start_time, end_time in peak_times:
            if start_time <= end_time:  # 同一天
                if start_time <= now_time <= end_time:
                    return True
            else:  # 跨天
                if now_time >= start_time or now_time <= end_time:
                    return True
        
        return False


# 创建一个全局单例
chat_frequency_analyzer = ChatFrequencyAnalyzer()

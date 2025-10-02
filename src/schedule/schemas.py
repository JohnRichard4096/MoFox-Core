# mmc/src/schedule/schemas.py

from datetime import datetime, time

from pydantic import BaseModel, validator


class ScheduleItem(BaseModel):
    """单个日程项的Pydantic模型"""

    time_range: str
    activity: str

    @validator("time_range")
    def validate_time_range(cls, v):
        """验证时间范围格式"""
        if not v or "-" not in v:
            raise ValueError("时间范围必须包含'-'分隔符")

        try:
            start_str, end_str = v.split("-", 1)
            start_str = start_str.strip()
            end_str = end_str.strip()

            # 验证时间格式
            datetime.strptime(start_str, "%H:%M")
            datetime.strptime(end_str, "%H:%M")

            return v
        except ValueError as e:
            raise ValueError(f"时间格式无效，应为HH:MM-HH:MM格式: {e}") from e

    @validator("activity")
    def validate_activity(cls, v):
        """验证活动描述"""
        if not v or not v.strip():
            raise ValueError("活动描述不能为空")
        return v.strip()


class ScheduleData(BaseModel):
    """完整日程数据的Pydantic模型"""

    schedule: list[ScheduleItem]

    @validator("schedule")
    def validate_schedule_completeness(cls, v):
        """验证日程是否覆盖24小时"""
        if not v:
            raise ValueError("日程不能为空")

        # 收集所有时间段
        time_ranges = []
        for item in v:
            try:
                start_str, end_str = item.time_range.split("-", 1)
                start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
                end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
                time_ranges.append((start_time, end_time))
            except ValueError:
                continue

        # 检查是否覆盖24小时
        if not cls._check_24_hour_coverage(time_ranges):
            raise ValueError("日程必须覆盖完整的24小时")

        return v

    @staticmethod
    def _check_24_hour_coverage(time_ranges: list[tuple]) -> bool:
        """检查时间段是否覆盖24小时"""
        if not time_ranges:
            return False

        # 将时间转换为分钟数进行计算
        def time_to_minutes(t: time) -> int:
            return t.hour * 60 + t.minute

        # 创建覆盖情况数组 (1440分钟 = 24小时)
        covered = [False] * 1440

        for start_time, end_time in time_ranges:
            start_min = time_to_minutes(start_time)
            end_min = time_to_minutes(end_time)

            if start_min <= end_min:
                # 同一天内的时间段
                for i in range(start_min, end_min):
                    if i < 1440:
                        covered[i] = True
            else:
                # 跨天的时间段
                for i in range(start_min, 1440):
                    covered[i] = True
                for i in range(0, end_min):
                    covered[i] = True

        # 检查是否所有分钟都被覆盖
        return all(covered)

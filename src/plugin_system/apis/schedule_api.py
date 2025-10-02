"""
日程表与月度计划API模块

专门负责日程和月度计划信息的查询与管理，采用标准Python包设计模式
所有对外接口均为异步函数，以便于插件开发者在异步环境中使用。

使用方式：
    import asyncio
    from src.plugin_system.apis import schedule_api

    async def main():
        # 获取今日日程
        today_schedule = await schedule_api.get_today_schedule()
        if today_schedule:
            print("今天的日程:", today_schedule)

        # 获取当前活动
        current_activity = await schedule_api.get_current_activity()
        if current_activity:
            print("当前活动:", current_activity)

        # 获取本月月度计划
        from datetime import datetime
        this_month = datetime.now().strftime("%Y-%m")
        plans = await schedule_api.get_monthly_plans(this_month)
        if plans:
            print(f"{this_month} 的月度计划:", [p.plan_text for p in plans])

    asyncio.run(main())
"""

from datetime import datetime
from typing import Any

from src.common.database.sqlalchemy_models import MonthlyPlan
from src.common.logger import get_logger
from src.schedule.database import get_active_plans_for_month
from src.schedule.schedule_manager import schedule_manager

logger = get_logger("schedule_api")


class ScheduleAPI:
    """日程表与月度计划API - 负责日程和计划信息的查询与管理"""

    @staticmethod
    async def get_today_schedule() -> list[dict[str, Any]] | None:
        """(异步) 获取今天的日程安排

        Returns:
            Optional[List[Dict[str, Any]]]: 今天的日程列表，如果未生成或未启用则返回None
        """
        try:
            logger.debug("[ScheduleAPI] 正在获取今天的日程安排...")
            return schedule_manager.today_schedule
        except Exception as e:
            logger.error(f"[ScheduleAPI] 获取今日日程失败: {e}")
            return None

    @staticmethod
    async def get_current_activity() -> str | None:
        """(异步) 获取当前正在进行的活动

        Returns:
            Optional[str]: 当前活动名称，如果没有则返回None
        """
        try:
            logger.debug("[ScheduleAPI] 正在获取当前活动...")
            return schedule_manager.get_current_activity()
        except Exception as e:
            logger.error(f"[ScheduleAPI] 获取当前活动失败: {e}")
            return None

    @staticmethod
    async def regenerate_schedule() -> bool:
        """(异步) 触发后台重新生成今天的日程

        Returns:
            bool: 是否成功触发
        """
        try:
            logger.info("[ScheduleAPI] 正在触发后台重新生成日程...")
            await schedule_manager.generate_and_save_schedule()
            return True
        except Exception as e:
            logger.error(f"[ScheduleAPI] 触发日程重新生成失败: {e}")
            return False

    @staticmethod
    async def get_monthly_plans(target_month: str | None = None) -> list[MonthlyPlan]:
        """(异步) 获取指定月份的有效月度计划

        Args:
            target_month (Optional[str]): 目标月份，格式为 "YYYY-MM"。如果为None，则使用当前月份。

        Returns:
            List[MonthlyPlan]: 月度计划对象列表
        """
        if target_month is None:
            target_month = datetime.now().strftime("%Y-%m")
        try:
            logger.debug(f"[ScheduleAPI] 正在获取 {target_month} 的月度计划...")
            return await get_active_plans_for_month(target_month)
        except Exception as e:
            logger.error(f"[ScheduleAPI] 获取 {target_month} 月度计划失败: {e}")
            return []

    @staticmethod
    async def ensure_monthly_plans(target_month: str | None = None) -> bool:
        """(异步) 确保指定月份存在月度计划，如果不存在则触发生成

        Args:
            target_month (Optional[str]): 目标月份，格式为 "YYYY-MM"。如果为None，则使用当前月份。

        Returns:
            bool: 操作是否成功 (如果已存在或成功生成)
        """
        if target_month is None:
            target_month = datetime.now().strftime("%Y-%m")
        try:
            logger.info(f"[ScheduleAPI] 正在确保 {target_month} 的月度计划存在...")
            return await schedule_manager.plan_manager.ensure_and_generate_plans_if_needed(target_month)
        except Exception as e:
            logger.error(f"[ScheduleAPI] 确保 {target_month} 月度计划失败: {e}")
            return False

    @staticmethod
    async def archive_monthly_plans(target_month: str | None = None) -> bool:
        """(异步) 归档指定月份的月度计划

        Args:
            target_month (Optional[str]): 目标月份，格式为 "YYYY-MM"。如果为None，则使用当前月份。

        Returns:
            bool: 操作是否成功
        """
        if target_month is None:
            target_month = datetime.now().strftime("%Y-%m")
        try:
            logger.info(f"[ScheduleAPI] 正在归档 {target_month} 的月度计划...")
            await schedule_manager.plan_manager.archive_current_month_plans(target_month)
            return True
        except Exception as e:
            logger.error(f"[ScheduleAPI] 归档 {target_month} 月度计划失败: {e}")
            return False


# =============================================================================
# 模块级别的便捷函数 (全部为异步)
# =============================================================================


async def get_today_schedule() -> list[dict[str, Any]] | None:
    """(异步) 获取今天的日程安排的便捷函数"""
    return await ScheduleAPI.get_today_schedule()


async def get_current_activity() -> str | None:
    """(异步) 获取当前正在进行的活动的便捷函数"""
    return await ScheduleAPI.get_current_activity()


async def regenerate_schedule() -> bool:
    """(异步) 触发后台重新生成今天的日程的便捷函数"""
    return await ScheduleAPI.regenerate_schedule()


async def get_monthly_plans(target_month: str | None = None) -> list[MonthlyPlan]:
    """(异步) 获取指定月份的有效月度计划的便捷函数"""
    return await ScheduleAPI.get_monthly_plans(target_month)


async def ensure_monthly_plans(target_month: str | None = None) -> bool:
    """(异步) 确保指定月份存在月度计划的便捷函数"""
    return await ScheduleAPI.ensure_monthly_plans(target_month)


async def archive_monthly_plans(target_month: str | None = None) -> bool:
    """(异步) 归档指定月份的月度计划的便捷函数"""
    return await ScheduleAPI.archive_monthly_plans(target_month)

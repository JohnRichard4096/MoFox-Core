import asyncio
from datetime import datetime, timedelta

from src.common.logger import get_logger
from src.manager.async_task_manager import AsyncTask, async_task_manager

from .plan_manager import PlanManager

logger = get_logger("monthly_plan_manager")


class MonthlyPlanManager:
    def __init__(self):
        self.plan_manager = PlanManager()
        self.monthly_task_started = False

    async def initialize(self):
        logger.info("正在初始化月度计划管理器...")
        await self.start_monthly_plan_generation()
        logger.info("月度计划管理器初始化成功")

    async def start_monthly_plan_generation(self):
        if not self.monthly_task_started:
            logger.info(" 正在启动每月月度计划生成任务...")
            task = MonthlyPlanGenerationTask(self)
            await async_task_manager.add_task(task)
            self.monthly_task_started = True
            logger.info(" 每月月度计划生成任务已成功启动。")
            logger.info(" 执行启动时月度计划检查...")
            await self.plan_manager.ensure_and_generate_plans_if_needed()
        else:
            logger.info(" 每月月度计划生成任务已在运行中。")

    async def ensure_and_generate_plans_if_needed(self, target_month: str | None = None) -> bool:
        return await self.plan_manager.ensure_and_generate_plans_if_needed(target_month)


class MonthlyPlanGenerationTask(AsyncTask):
    def __init__(self, monthly_plan_manager: MonthlyPlanManager):
        super().__init__(task_name="MonthlyPlanGenerationTask")
        self.monthly_plan_manager = monthly_plan_manager

    async def run(self):
        while True:
            try:
                now = datetime.now()
                if now.month == 12:
                    next_month = datetime(now.year + 1, 1, 1)
                else:
                    next_month = datetime(now.year, now.month + 1, 1)
                sleep_seconds = (next_month - now).total_seconds()
                logger.info(
                    f" 下一次月度计划生成任务将在 {sleep_seconds:.2f} 秒后运行 (北京时间 {next_month.strftime('%Y-%m-%d %H:%M:%S')})"
                )
                await asyncio.sleep(sleep_seconds)
                last_month = (next_month - timedelta(days=1)).strftime("%Y-%m")
                await self.monthly_plan_manager.plan_manager.archive_current_month_plans(last_month)
                current_month = next_month.strftime("%Y-%m")
                logger.info(f" 到达月初，开始生成 {current_month} 的月度计划...")
                await self.monthly_plan_manager.plan_manager._generate_monthly_plans_logic(current_month)
            except asyncio.CancelledError:
                logger.info(" 每月月度计划生成任务被取消。")
                break
            except Exception as e:
                logger.error(f" 每月月度计划生成任务发生未知错误: {e}")
                await asyncio.sleep(3600)


monthly_plan_manager = MonthlyPlanManager()

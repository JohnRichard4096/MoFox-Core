"""消息兴趣值计算组件管理器

管理消息兴趣值计算组件，确保系统只能有一个兴趣值计算组件实例运行
"""

import asyncio
import time
from typing import TYPE_CHECKING

from src.common.logger import get_logger
from src.plugin_system.base.base_interest_calculator import BaseInterestCalculator, InterestCalculationResult

if TYPE_CHECKING:
    from src.common.data_models.database_data_model import DatabaseMessages

logger = get_logger("message_interest_manager")


class MessageInterestManager:
    """消息兴趣值计算组件管理器"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._current_calculator: BaseInterestCalculator | None = None
            self._calculator_lock = asyncio.Lock()
            self._last_calculation_time = 0.0
            self._total_calculations = 0
            self._failed_calculations = 0
            self._initialized = True

    async def initialize(self):
        """初始化管理器"""
        logger.info("消息兴趣值管理器已初始化")

    async def register_calculator(self, calculator: BaseInterestCalculator) -> bool:
        """注册兴趣值计算组件

        Args:
            calculator: 兴趣值计算组件实例

        Returns:
            bool: 注册是否成功
        """
        async with self._calculator_lock:
            try:
                # 如果已有组件在运行，先清理
                if self._current_calculator:
                    logger.info(f"替换现有消息兴趣值计算组件: {self._current_calculator.component_name}")
                    await self._current_calculator.cleanup()

                # 初始化新组件
                if await calculator.initialize():
                    self._current_calculator = calculator
                    logger.info(f"消息兴趣值计算组件注册成功: {calculator.component_name} v{calculator.component_version}")
                    return True
                else:
                    logger.error(f"消息兴趣值计算组件初始化失败: {calculator.component_name}")
                    return False

            except Exception as e:
                logger.error(f"注册消息兴趣值计算组件失败: {e}", exc_info=True)
                return False

    async def calculate_interest(self, message: "DatabaseMessages") -> InterestCalculationResult:
        """计算消息兴趣值

        Args:
            message: 数据库消息对象

        Returns:
            InterestCalculationResult: 计算结果
        """
        if not self._current_calculator:
            # 返回默认结果
            return InterestCalculationResult(
                success=False,
                message_id=getattr(message, 'message_id', ''),
                interest_value=0.3,
                error_message="没有可用的消息兴趣值计算组件"
            )

        start_time = time.time()
        self._total_calculations += 1

        try:
            # 使用组件的安全执行方法
            result = await self._current_calculator._safe_execute(message)

            if result.success:
                self._last_calculation_time = time.time()
                logger.debug(f"消息兴趣值计算完成: {result.interest_value:.3f} (耗时: {result.calculation_time:.3f}s)")
            else:
                self._failed_calculations += 1
                logger.warning(f"消息兴趣值计算失败: {result.error_message}")

            return result

        except Exception as e:
            self._failed_calculations += 1
            logger.error(f"消息兴趣值计算异常: {e}", exc_info=True)
            return InterestCalculationResult(
                success=False,
                message_id=getattr(message, 'message_id', ''),
                interest_value=0.0,
                error_message=f"计算异常: {str(e)}",
                calculation_time=time.time() - start_time
            )

    def get_current_calculator(self) -> BaseInterestCalculator | None:
        """获取当前活跃的兴趣值计算组件"""
        return self._current_calculator

    def get_statistics(self) -> dict:
        """获取管理器统计信息"""
        success_rate = 1.0 - (self._failed_calculations / max(1, self._total_calculations))

        stats = {
            "manager_statistics": {
                "total_calculations": self._total_calculations,
                "failed_calculations": self._failed_calculations,
                "success_rate": success_rate,
                "last_calculation_time": self._last_calculation_time,
                "current_calculator": self._current_calculator.component_name if self._current_calculator else None
            }
        }

        # 添加当前组件的统计信息
        if self._current_calculator:
            stats["calculator_statistics"] = self._current_calculator.get_statistics()

        return stats

    async def health_check(self) -> bool:
        """健康检查"""
        if not self._current_calculator:
            return False

        try:
            # 检查组件是否还活跃
            return self._current_calculator.is_enabled
        except Exception:
            return False

    def has_calculator(self) -> bool:
        """检查是否有可用的计算组件"""
        return self._current_calculator is not None and self._current_calculator.is_enabled


# 全局实例
_message_interest_manager = None


def get_message_interest_manager() -> MessageInterestManager:
    """获取消息兴趣值管理器实例"""
    global _message_interest_manager
    if _message_interest_manager is None:
        _message_interest_manager = MessageInterestManager()
    return _message_interest_manager
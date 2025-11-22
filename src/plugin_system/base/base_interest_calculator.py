"""兴趣值计算组件基类

提供兴趣值计算的标准接口，确保只能有一个兴趣值计算组件实例运行
"""

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.common.data_models.database_data_model import DatabaseMessages

from src.common.logger import get_logger
from src.plugin_system.base.component_types import ComponentType, InterestCalculatorInfo

logger = get_logger("base_interest_calculator")


class InterestCalculationResult:
    """兴趣值计算结果"""

    def __init__(
        self,
        success: bool,
        message_id: str,
        interest_value: float,
        should_take_action: bool = False,
        should_reply: bool = False,
        should_act: bool = False,
        error_message: str | None = None,
        calculation_time: float = 0.0,
    ):
        self.success = success
        self.message_id = message_id
        self.interest_value = interest_value
        self.should_take_action = should_take_action
        self.should_reply = should_reply
        self.should_act = should_act
        self.error_message = error_message
        self.calculation_time = calculation_time
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "success": self.success,
            "message_id": self.message_id,
            "interest_value": self.interest_value,
            "should_take_action": self.should_take_action,
            "should_reply": self.should_reply,
            "should_act": self.should_act,
            "error_message": self.error_message,
            "calculation_time": self.calculation_time,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"InterestCalculationResult("
            f"success={self.success}, "
            f"message_id={self.message_id}, "
            f"interest_value={self.interest_value:.3f}, "
            f"should_take_action={self.should_take_action}, "
            f"should_reply={self.should_reply}, "
            f"should_act={self.should_act})"
        )


class BaseInterestCalculator(ABC):
    """兴趣值计算组件基类

    所有兴趣值计算组件都必须继承此类，并实现 execute 方法
    系统确保只能有一个兴趣值计算组件实例运行
    """

    # 子类必须定义这些属性
    component_name: str = ""
    component_version: str = ""
    component_description: str = ""
    enabled_by_default: bool = True  # 是否默认启用

    def __init__(self, plugin_config: dict | None = None):
        self._enabled = False
        self._last_calculation_time = 0.0
        self._total_calculations = 0
        self._failed_calculations = 0
        self._average_calculation_time = 0.0
        if plugin_config is None:
            plugin_config = getattr(self.__class__, "plugin_config", {})

        self.plugin_config = plugin_config or {}

        # 验证必须定义的属性
        if not self.component_name:
            raise ValueError("子类必须定义 component_name 属性")
        if not self.component_version:
            raise ValueError("子类必须定义 component_version 属性")
        if not self.component_description:
            raise ValueError("子类必须定义 component_description 属性")

    @abstractmethod
    async def execute(self, message: "DatabaseMessages") -> InterestCalculationResult:
        """执行兴趣值计算

        Args:
            message: 数据库消息对象

        Returns:
            InterestCalculationResult: 计算结果
        """
        pass

    async def initialize(self) -> bool:
        """初始化组件

        Returns:
            bool: 初始化是否成功
        """
        try:
            self._enabled = True
            return True
        except Exception:
            self._enabled = False
            return False

    async def cleanup(self) -> bool:
        """清理组件资源

        Returns:
            bool: 清理是否成功
        """
        try:
            self._enabled = False
            return True
        except Exception:
            return False

    @property
    def is_enabled(self) -> bool:
        """组件是否已启用"""
        return self._enabled

    def get_statistics(self) -> dict:
        """获取组件统计信息"""
        return {
            "component_name": self.component_name,
            "component_version": self.component_version,
            "enabled": self._enabled,
            "total_calculations": self._total_calculations,
            "failed_calculations": self._failed_calculations,
            "success_rate": 1.0 - (self._failed_calculations / max(1, self._total_calculations)),
            "average_calculation_time": self._average_calculation_time,
            "last_calculation_time": self._last_calculation_time,
        }

    def _update_statistics(self, result: InterestCalculationResult):
        """更新统计信息"""
        self._total_calculations += 1
        if not result.success:
            self._failed_calculations += 1

        # 更新平均计算时间
        if self._total_calculations == 1:
            self._average_calculation_time = result.calculation_time
        else:
            alpha = 0.1  # 指数移动平均的平滑因子
            self._average_calculation_time = (
                alpha * result.calculation_time + (1 - alpha) * self._average_calculation_time
            )

        self._last_calculation_time = result.timestamp

    async def _safe_execute(self, message: "DatabaseMessages") -> InterestCalculationResult:
        """安全执行计算，包含统计和错误处理"""
        if not self._enabled:
            return InterestCalculationResult(
                success=False,
                message_id=getattr(message, "message_id", ""),
                interest_value=0.0,
                error_message="组件未启用",
            )

        start_time = time.time()
        try:
            result = await self.execute(message)
            result.calculation_time = time.time() - start_time
            self._update_statistics(result)
            return result
        except Exception as e:
            result = InterestCalculationResult(
                success=False,
                message_id=getattr(message, "message_id", ""),
                interest_value=0.0,
                error_message=f"计算执行失败: {e!s}",
                calculation_time=time.time() - start_time,
            )
            self._update_statistics(result)
            return result

    def get_config(self, key: str, default: Any = None) -> Any:
        """获取插件配置，支持嵌套键访问"""
        if not self.plugin_config:
            return default

        current = self.plugin_config
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    @classmethod
    def get_interest_calculator_info(cls) -> "InterestCalculatorInfo":
        """从类属性生成InterestCalculatorInfo

        遵循BaseCommand和BaseAction的设计模式，从类属性自动生成组件信息

        Returns:
            InterestCalculatorInfo: 生成的兴趣计算器信息对象
        """
        name = getattr(cls, "component_name", cls.__name__.lower().replace("calculator", ""))
        if "." in name:
            logger.error(f"InterestCalculator名称 '{name}' 包含非法字符 '.'，请使用下划线替代")
            raise ValueError(f"InterestCalculator名称 '{name}' 包含非法字符 '.'，请使用下划线替代")

        return InterestCalculatorInfo(
            name=name,
            component_type=ComponentType.INTEREST_CALCULATOR,
            description=getattr(cls, "component_description", cls.__doc__ or "兴趣度计算器"),
            enabled_by_default=getattr(cls, "enabled_by_default", True),
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.component_name}, "
            f"version={self.component_version}, "
            f"enabled={self._enabled})"
        )

"""
反注入系统管理命令插件

提供管理和监控反注入系统的命令接口，包括：
- 系统状态查看
- 配置修改
- 统计信息查看
- 测试功能
"""

from src.chat.antipromptinjector import get_anti_injector
from src.common.logger import get_logger
from src.plugin_system.base import BaseCommand

logger = get_logger("anti_injector.commands")


class AntiInjectorStatusCommand(BaseCommand):
    """反注入系统状态查看命令"""

    command_name = "反注入状态"  # 命令名称，作为唯一标识符
    command_description = "查看反注入系统状态和统计信息"  # 命令描述
    command_pattern = r"^/反注入状态$"  # 命令匹配的正则表达式

    async def execute(self) -> tuple[bool, str, bool]:
        try:
            anti_injector = get_anti_injector()
            stats = await anti_injector.get_stats()

            # 检查反注入系统是否禁用
            if stats.get("status") == "disabled":
                await self.send_text("❌ 反注入系统未启用\n\n💡 请在配置文件中启用反注入功能后重试")
                return True, "反注入系统未启用", True

            if stats.get("error"):
                await self.send_text(f"❌ 获取状态失败: {stats['error']}")
                return False, f"获取状态失败: {stats['error']}", True

            status_text = f"""🛡️ 反注入系统状态报告

📊 运行统计:
• 运行时间: {stats["uptime"]}
• 处理消息总数: {stats["total_messages"]}
• 检测到注入: {stats["detected_injections"]}
• 阻止消息: {stats["blocked_messages"]}
• 加盾消息: {stats["shielded_messages"]}

📈 性能指标:
• 检测率: {stats["detection_rate"]}
• 平均处理时间: {stats["average_processing_time"]}
• 最后处理时间: {stats["last_processing_time"]}

⚠️ 错误计数: {stats["error_count"]}"""
            await self.send_text(status_text)
            return True, status_text, True

        except Exception as e:
            logger.error(f"获取反注入系统状态失败: {e}")
            await self.send_text(f"获取状态失败: {e!s}")
            return False, f"获取状态失败: {e!s}", True

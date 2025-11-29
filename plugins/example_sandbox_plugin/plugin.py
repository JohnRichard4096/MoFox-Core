"""
示例沙盒插件

演示如何创建一个在沙盒环境中运行的安全插件
"""
from src.plugin_system import register_plugin
from src.plugin_system.base.component_types import ActionInfo, ComponentType
from src.plugin_system.base.sandbox_components import SandboxAction, SandboxCommand
from src.plugin_system.base.sandbox_plugin import SandboxPlugin


# 定义一个沙盒Action
class ExampleSandboxAction(SandboxAction):
    """示例沙盒Action - 计算消息中数字的平方"""

    action_name = "example_sandbox_action"
    activation_keywords = ["计算平方", "平方"]
    priority = 50

    sandbox_timeout = 5.0  # 5秒超时

    def get_action_code(self) -> str:
        """返回要在沙盒中执行的代码"""
        return """
import re

# 从消息文本中提取数字
numbers = re.findall(r'\\d+', message_text)

if numbers:
    # 计算第一个数字的平方
    num = int(numbers[0])
    square = num * num
    
    # 设置返回结果
    __result__ = f"{num} 的平方是 {square}"
    api['log'](f"计算 {num} 的平方 = {square}")
else:
    __result__ = "没有找到数字"
"""

    async def _handle_sandbox_result(self, result, chat_stream) -> bool:
        """处理沙盒执行结果"""
        if result.get("success"):
            result_text = result.get("result", "")
            if result_text:
                # 发送结果到聊天流
                from src.plugin_system.apis import send_api

                await send_api.text_to_stream(
                    text=result_text,
                    stream_id=chat_stream.stream_id,
                )
                return True
        return False

    @classmethod
    def get_action_info(cls) -> ActionInfo:
        return ActionInfo(
            name=cls.action_name,
            component_type=ComponentType.ACTION,
            activation_keywords=cls.activation_keywords,
            description="在沙盒中计算数字的平方",
        )


# 定义一个沙盒Command
class ExampleSandboxCommand(SandboxCommand):
    """示例沙盒Command - 生成随机数"""

    command_name = "random"
    command_description = "生成随机数"
    command_usage = "/random [最大值]"

    sandbox_timeout = 3.0

    def get_command_code(self) -> str:
        """返回要在沙盒中执行的代码"""
        return """
import random

# 解析参数
max_value = 100  # 默认最大值

if args.strip():
    try:
        max_value = int(args.strip())
    except:
        __result__ = "参数必须是数字"
    else:
        # 生成随机数
        rand_num = random.randint(1, max_value)
        __result__ = f"生成的随机数: {rand_num} (范围: 1-{max_value})"
        api['log'](f"生成随机数 {rand_num}")
else:
    rand_num = random.randint(1, max_value)
    __result__ = f"生成的随机数: {rand_num}"
"""


# 定义沙盒插件
@register_plugin
class ExampleSandboxPlugin(SandboxPlugin):
    """示例沙盒插件"""

    plugin_name = "example_sandbox_plugin"
    config_file_name = "example_sandbox_config.toml"
    enable_plugin = True

    def get_plugin_components(self) -> list:
        """返回插件组件列表"""
        return [
            (ExampleSandboxAction.get_action_info(), ExampleSandboxAction),
            # Command暂时不在沙盒中实现，因为PlusCommand需要特殊处理
            # (ExampleSandboxCommand.get_command_info(), ExampleSandboxCommand),
        ]

    async def on_plugin_loaded(self):
        """插件加载时的钩子"""
        await super().on_plugin_loaded()
        print(f"[{self.plugin_name}] 沙盒插件已加载")

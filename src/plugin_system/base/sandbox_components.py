"""
沙盒Action和Command组件

为沙盒插件提供安全的Action和Command实现
"""
from typing import Any

from src.chat.message_receive.chat_stream import ChatStream
from src.plugin_system.base.plus_command import CommandArgs
from src.common.logger import get_logger
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.plus_command import PlusCommand
from src.plugin_system.core.sandbox_environment import get_sandbox_environment

logger = get_logger("sandbox_components")


class SandboxAction(BaseAction):
    """沙盒Action基类

    在沙盒环境中执行的Action组件
    """

    # 沙盒执行超时时间（秒）
    sandbox_timeout: float = 10.0

    async def execute(self) -> tuple[bool, str]:
        """执行Action（在沙盒中）

        Returns:
            tuple[bool, str]: (是否执行成功, 回复文本)
        """
        try:
            # 从实例属性获取 chat_stream
            chat_stream = self.chat_stream
            
            # 准备沙盒执行上下文
            context = self._prepare_sandbox_context(chat_stream)

            # 获取沙盒环境
            sandbox = get_sandbox_environment()

            # 获取要执行的代码
            code = self.get_action_code()

            # 在沙盒中执行
            result = await sandbox.execute_async(
                code=code,
                context=context,
                timeout=self.sandbox_timeout,
            )

            if result.get("success"):
                # 处理执行结果
                reply_text = await self._handle_sandbox_result(result, chat_stream)
                return True, reply_text
            else:
                error_msg = f"{result.get('error_type')} - {result.get('error')}"
                logger.error(f"[SandboxAction:{self.action_name}] 执行失败: {error_msg}")
                return False, f"沙盒执行失败: {error_msg}"

        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"[SandboxAction:{self.action_name}] 异常: {e}")
            return False, f"沙盒执行异常: {e}"

    def _prepare_sandbox_context(self, chat_stream: ChatStream) -> dict[str, Any]:
        """准备沙盒执行上下文

        子类可以覆盖此方法来提供自定义上下文

        Args:
            chat_stream: 聊天流对象

        Returns:
            dict[str, Any]: 上下文字典
        """
        # 获取最后一条消息
        last_message = chat_stream.context.get_last_message()
        
        # 只提供安全的、只读的信息
        context: dict[str, Any] = {
            "message_text": last_message.processed_plain_text if last_message else "",
            "user_id": chat_stream.user_info.user_id if chat_stream.user_info else "",
            "group_id": chat_stream.group_info.group_id if chat_stream.group_info else "",
            "platform": chat_stream.platform,
        }

        # 添加安全的API接口
        context["api"] = self._get_safe_api()

        return context

    def _get_safe_api(self) -> dict[str, Any]:
        """获取安全的API接口

        返回插件可以安全调用的API函数

        Returns:
            dict[str, Any]: API函数字典
        """
        safe_api: dict[str, Any] = {
            # 日志函数
            "log": lambda msg: logger.info(f"[{self.action_name}] {msg}"),
            # 其他安全的API可以在这里添加
        }

        return safe_api

    def get_action_code(self) -> str:
        """获取要在沙盒中执行的代码

        子类必须实现此方法

        Returns:
            str: Python代码字符串
        """
        raise NotImplementedError("子类必须实现 get_action_code 方法")

    async def _handle_sandbox_result(self, result: dict[str, Any], chat_stream: ChatStream) -> str:
        """处理沙盒执行结果

        子类可以覆盖此方法来处理执行结果

        Args:
            result: 沙盒执行结果
            chat_stream: 聊天流对象

        Returns:
            str: 回复文本
        """
        # 默认实现：返回沙盒执行的结果
        _ = chat_stream  # 标记为已使用，子类可能需要
        return str(result.get("result", ""))


class SandboxCommand(PlusCommand):
    """沙盒Command基类

    在沙盒环境中执行的Command组件
    """

    # 沙盒执行超时时间（秒）
    sandbox_timeout: float = 10.0

    async def execute(self, args: CommandArgs) -> tuple[bool, str | None, bool]:
        """执行Command（在沙盒中）

        Args:
            args: 解析后的命令参数

        Returns:
            tuple[bool, str | None, bool]: (是否成功, 返回消息, 是否拦截消息)
        """
        try:
            # 将 CommandArgs 转换为字符串参数
            args_str = args.get_raw()
            
            # 准备沙盒执行上下文
            context = self._prepare_sandbox_context(args_str)

            # 获取沙盒环境
            sandbox = get_sandbox_environment()

            # 获取要执行的代码
            code = self.get_command_code()

            # 在沙盒中执行
            result = await sandbox.execute_async(
                code=code,
                context=context,
                timeout=self.sandbox_timeout,
            )

            if result.get("success"):
                # 获取返回消息
                output = result.get("result") or result.get("output", "")
                return True, str(output), True
            else:
                error_msg = f"{result.get('error_type')}: {result.get('error')}"
                logger.error(f"[SandboxCommand:{self.command_name}] 执行失败: {error_msg}")
                return False, f"命令执行失败: {error_msg}", True

        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"[SandboxCommand:{self.command_name}] 异常: {e}")
            return False, f"命令执行异常: {e!s}", True

    def _prepare_sandbox_context(self, args: str) -> dict[str, Any]:
        """准备沙盒执行上下文

        子类可以覆盖此方法来提供自定义上下文

        Args:
            args: 命令参数

        Returns:
            dict[str, Any]: 上下文字典
        """
        # 只提供安全的信息
        context: dict[str, Any] = {
            "args": args,
            "command_name": self.command_name,
        }

        # 添加安全的API接口
        context["api"] = self._get_safe_api()

        return context

    def _get_safe_api(self) -> dict[str, Any]:
        """获取安全的API接口

        返回插件可以安全调用的API函数

        Returns:
            dict[str, Any]: API函数字典
        """
        safe_api: dict[str, Any] = {
            # 日志函数
            "log": lambda msg: logger.info(f"[{self.command_name}] {msg}"),
        }

        return safe_api

    def get_command_code(self) -> str:
        """获取要在沙盒中执行的代码

        子类必须实现此方法

        Returns:
            str: Python代码字符串
        """
        raise NotImplementedError("子类必须实现 get_command_code 方法")

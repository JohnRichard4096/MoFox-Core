"""
Adapter 管理器

负责管理所有注册的适配器，支持子进程自动启动和生命周期管理。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from src.plugin_system.base.base_adapter import BaseAdapter

from src.common.logger import get_logger

logger = get_logger("adapter_manager")


class AdapterProcess:
    """适配器子进程包装器"""

    def __init__(
        self,
        adapter_name: str,
        entry_path: Path,
        python_executable: Optional[str] = None,
    ):
        self.adapter_name = adapter_name
        self.entry_path = entry_path
        self.python_executable = python_executable or sys.executable
        self.process: Optional[subprocess.Popen] = None
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self) -> bool:
        """启动适配器子进程"""
        try:
            logger.info(f"启动适配器子进程: {self.adapter_name}")
            logger.debug(f"Python: {self.python_executable}")
            logger.debug(f"Entry: {self.entry_path}")

            # 启动子进程
            self.process = subprocess.Popen(
                [self.python_executable, str(self.entry_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            # 启动监控任务
            self._monitor_task = asyncio.create_task(self._monitor_process())

            logger.info(f"适配器 {self.adapter_name} 子进程已启动 (PID: {self.process.pid})")
            return True

        except Exception as e:
            logger.error(f"启动适配器 {self.adapter_name} 子进程失败: {e}", exc_info=True)
            return False

    async def stop(self) -> None:
        """停止适配器子进程"""
        if not self.process:
            return

        logger.info(f"停止适配器子进程: {self.adapter_name} (PID: {self.process.pid})")

        try:
            # 取消监控任务
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass

            # 终止进程
            self.process.terminate()

            # 等待进程退出（最多等待5秒）
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self.process.wait),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"适配器 {self.adapter_name} 未能在5秒内退出，强制终止")
                self.process.kill()
                await asyncio.to_thread(self.process.wait)

            logger.info(f"适配器 {self.adapter_name} 子进程已停止")

        except Exception as e:
            logger.error(f"停止适配器 {self.adapter_name} 子进程时出错: {e}", exc_info=True)
        finally:
            self.process = None

    async def _monitor_process(self) -> None:
        """监控子进程状态"""
        if not self.process:
            return

        try:
            # 在后台线程中等待进程退出
            return_code = await asyncio.to_thread(self.process.wait)

            if return_code != 0:
                logger.error(
                    f"适配器 {self.adapter_name} 子进程异常退出 (返回码: {return_code})"
                )

                # 读取 stderr 输出
                if self.process.stderr:
                    stderr = self.process.stderr.read()
                    if stderr:
                        logger.error(f"错误输出:\n{stderr}")
            else:
                logger.info(f"适配器 {self.adapter_name} 子进程正常退出")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"监控适配器 {self.adapter_name} 子进程时出错: {e}", exc_info=True)

    def is_running(self) -> bool:
        """检查进程是否正在运行"""
        if not self.process:
            return False
        return self.process.poll() is None


class AdapterManager:
    """适配器管理器"""

    def __init__(self):
        self._adapters: Dict[str, BaseAdapter] = {}
        self._adapter_processes: Dict[str, AdapterProcess] = {}
        self._in_process_adapters: Dict[str, BaseAdapter] = {}

    def register_adapter(self, adapter: BaseAdapter) -> None:
        """
        注册适配器
        
        Args:
            adapter: 要注册的适配器实例
        """
        adapter_name = adapter.adapter_name

        if adapter_name in self._adapters:
            logger.warning(f"适配器 {adapter_name} 已经注册，将被覆盖")

        self._adapters[adapter_name] = adapter
        logger.info(f"已注册适配器: {adapter_name} v{adapter.adapter_version}")

    async def start_adapter(self, adapter_name: str) -> bool:
        """
        启动指定的适配器
        
        Args:
            adapter_name: 适配器名称
            
        Returns:
            bool: 是否成功启动
        """
        adapter = self._adapters.get(adapter_name)
        if not adapter:
            logger.error(f"适配器 {adapter_name} 未注册")
            return False

        # 检查是否需要在子进程中运行
        if adapter.run_in_subprocess:
            return await self._start_adapter_subprocess(adapter)
        else:
            return await self._start_adapter_in_process(adapter)

    async def _start_adapter_subprocess(self, adapter: BaseAdapter) -> bool:
        """在子进程中启动适配器"""
        adapter_name = adapter.adapter_name

        # 获取子进程入口脚本
        entry_path = adapter.get_subprocess_entry_path()
        if not entry_path:
            logger.error(
                f"适配器 {adapter_name} 配置为子进程运行，但未提供有效的入口脚本"
            )
            return False

        # 创建并启动子进程
        adapter_process = AdapterProcess(adapter_name, entry_path)
        success = await adapter_process.start()

        if success:
            self._adapter_processes[adapter_name] = adapter_process

        return success

    async def _start_adapter_in_process(self, adapter: BaseAdapter) -> bool:
        """在主进程中启动适配器"""
        adapter_name = adapter.adapter_name

        try:
            await adapter.start()
            self._in_process_adapters[adapter_name] = adapter
            logger.info(f"适配器 {adapter_name} 已在主进程中启动")
            return True
        except Exception as e:
            logger.error(f"在主进程中启动适配器 {adapter_name} 失败: {e}", exc_info=True)
            return False

    async def stop_adapter(self, adapter_name: str) -> None:
        """
        停止指定的适配器
        
        Args:
            adapter_name: 适配器名称
        """
        # 检查是否在子进程中运行
        if adapter_name in self._adapter_processes:
            adapter_process = self._adapter_processes.pop(adapter_name)
            await adapter_process.stop()

        # 检查是否在主进程中运行
        if adapter_name in self._in_process_adapters:
            adapter = self._in_process_adapters.pop(adapter_name)
            try:
                await adapter.stop()
                logger.info(f"适配器 {adapter_name} 已从主进程中停止")
            except Exception as e:
                logger.error(f"停止适配器 {adapter_name} 时出错: {e}", exc_info=True)

    async def start_all_adapters(self) -> None:
        """启动所有注册的适配器"""
        logger.info(f"开始启动 {len(self._adapters)} 个适配器...")

        for adapter_name in list(self._adapters.keys()):
            await self.start_adapter(adapter_name)

    async def stop_all_adapters(self) -> None:
        """停止所有适配器"""
        logger.info("停止所有适配器...")

        # 停止所有子进程适配器
        for adapter_name in list(self._adapter_processes.keys()):
            await self.stop_adapter(adapter_name)

        # 停止所有主进程适配器
        for adapter_name in list(self._in_process_adapters.keys()):
            await self.stop_adapter(adapter_name)

        logger.info("所有适配器已停止")

    def get_adapter(self, adapter_name: str) -> Optional[BaseAdapter]:
        """
        获取适配器实例
        
        Args:
            adapter_name: 适配器名称
            
        Returns:
            BaseAdapter | None: 适配器实例，如果不存在则返回 None
        """
        # 只返回在主进程中运行的适配器
        return self._in_process_adapters.get(adapter_name)

    def list_adapters(self) -> Dict[str, Dict[str, any]]:
        """
        列出所有适配器的状态
        
        Returns:
            Dict: 适配器状态信息
        """
        result = {}

        for adapter_name, adapter in self._adapters.items():
            status = {
                "name": adapter_name,
                "version": adapter.adapter_version,
                "platform": adapter.platform,
                "run_in_subprocess": adapter.run_in_subprocess,
                "running": False,
                "location": "unknown",
            }

            # 检查运行状态
            if adapter_name in self._adapter_processes:
                process = self._adapter_processes[adapter_name]
                status["running"] = process.is_running()
                status["location"] = "subprocess"
                if process.process:
                    status["pid"] = process.process.pid

            elif adapter_name in self._in_process_adapters:
                status["running"] = True
                status["location"] = "in-process"

            result[adapter_name] = status

        return result


# 全局单例
_adapter_manager: Optional[AdapterManager] = None


def get_adapter_manager() -> AdapterManager:
    """获取适配器管理器单例"""
    global _adapter_manager
    if _adapter_manager is None:
        _adapter_manager = AdapterManager()
    return _adapter_manager


__all__ = ["AdapterManager", "AdapterProcess", "get_adapter_manager"]

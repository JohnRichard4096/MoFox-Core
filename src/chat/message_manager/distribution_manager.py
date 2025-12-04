"""
流循环管理器 - 基于 Generator + Tick 的事件驱动模式

采用异步生成器替代无限循环任务，实现更简洁可控的消息处理流程。

核心概念：
- ConversationTick: 表示一次待处理的会话事件
- conversation_loop: 异步生成器，按需产出 Tick 事件
- run_chat_stream: 驱动器，消费 Tick 并调用 Chatter
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Awaitable

from src.chat.chatter_manager import ChatterManager
from src.chat.energy_system import energy_manager
from src.common.logger import get_logger
from src.config.config import global_config
from src.chat.message_receive.chat_stream import get_chat_manager

if TYPE_CHECKING:
    from src.chat.message_receive.chat_stream import ChatStream
    from src.common.data_models.message_manager_data_model import StreamContext

logger = get_logger("stream_loop_manager")


# ============================================================================
# Tick 数据模型
# ============================================================================


@dataclass
class ConversationTick:
    """
    会话事件标记 - 表示一次待处理的会话事件
    
    这是一个轻量级的事件信号，不存储消息数据。
    未读消息由 StreamContext 管理，能量值由 energy_manager 管理。
    """
    stream_id: str
    tick_time: float = field(default_factory=time.time)
    force_dispatch: bool = False  # 是否为强制分发（未读消息超阈值）
    tick_count: int = 0  # 当前流的 tick 计数


# ============================================================================
# 异步生成器 - 核心循环逻辑
# ============================================================================


async def conversation_loop(
    stream_id: str,
    get_context_func: Callable[[str], Awaitable["StreamContext | None"]],
    calculate_interval_func: Callable[[str, bool], Awaitable[float]],
    flush_cache_func: Callable[[str], Awaitable[None]],
    check_force_dispatch_func: Callable[["StreamContext", int], bool],
    is_running_func: Callable[[], bool],
) -> AsyncIterator[ConversationTick]:
    """
    会话循环生成器 - 按需产出 Tick 事件
    
    替代原有的无限循环任务，改为事件驱动的生成器模式。
    只有调用 __anext__() 时才会执行，完全由消费者控制节奏。
    
    Args:
        stream_id: 流ID
        get_context_func: 获取 StreamContext 的异步函数
        calculate_interval_func: 计算等待间隔的异步函数
        flush_cache_func: 刷新缓存消息的异步函数
        check_force_dispatch_func: 检查是否需要强制分发的函数
        is_running_func: 检查是否继续运行的函数
        
    Yields:
        ConversationTick: 会话事件
    """
    tick_count = 0
    last_interval = None
    
    while is_running_func():
        try:
            # 1. 获取流上下文
            context = await get_context_func(stream_id)
            if not context:
                logger.warning(f" [生成器] stream={stream_id[:8]}, 无法获取流上下文")
                await asyncio.sleep(10.0)
                continue
            
            # 2. 刷新缓存消息到未读列表
            await flush_cache_func(stream_id)
            
            # 3. 检查是否有消息需要处理
            unread_messages = context.get_unread_messages()
            unread_count = len(unread_messages) if unread_messages else 0
            
            # 4. 检查是否需要强制分发
            force_dispatch = check_force_dispatch_func(context, unread_count)
            
            # 5. 如果有消息，产出 Tick
            if unread_count > 0 or force_dispatch:
                tick_count += 1
                yield ConversationTick(
                    stream_id=stream_id,
                    force_dispatch=force_dispatch,
                    tick_count=tick_count,
                )
            
            # 6. 计算并等待下次检查间隔
            has_messages = unread_count > 0
            interval = await calculate_interval_func(stream_id, has_messages)
            
            # 只在间隔发生变化时输出日志
            if last_interval is None or abs(interval - last_interval) > 0.01:
                logger.debug(f"[生成器] stream={stream_id[:8]}, 等待间隔: {interval:.2f}s")
                last_interval = interval
            
            await asyncio.sleep(interval)
            
        except asyncio.CancelledError:
            logger.info(f" [生成器] stream={stream_id[:8]}, 被取消")
            break
        except Exception as e:
            logger.error(f" [生成器] stream={stream_id[:8]}, 出错: {e}")
            await asyncio.sleep(5.0)


# ============================================================================
# 聊天流驱动器
# ============================================================================


async def run_chat_stream(
    stream_id: str,
    manager: "StreamLoopManager",
) -> None:
    """
    聊天流驱动器 - 消费 Tick 事件并调用 Chatter
    
    替代原有的 _stream_loop_worker，结构更清晰。
    
    Args:
        stream_id: 流ID
        manager: StreamLoopManager 实例
    """
    task_id = id(asyncio.current_task())
    logger.debug(f" [驱动器] stream={stream_id[:8]}, 任务ID={task_id}, 启动")
    
    try:
        # 创建生成器
        tick_generator = conversation_loop(
            stream_id=stream_id,
            get_context_func=manager._get_stream_context,
            calculate_interval_func=manager._calculate_interval,
            flush_cache_func=manager._flush_cached_messages_to_unread,
            check_force_dispatch_func=manager._needs_force_dispatch_for_context,
            is_running_func=lambda: manager.is_running,
        )
        
        # 消费 Tick 事件
        async for tick in tick_generator:
            try:
                # 获取上下文
                context = await manager._get_stream_context(stream_id)
                if not context:
                    continue
                
                # 并发保护：检查是否正在处理
                if context.is_chatter_processing:
                    if manager._recover_stale_chatter_state(stream_id, context):
                        logger.warning(f" [驱动器] stream={stream_id[:8]}, 处理标志残留已修复")
                    else:
                        logger.debug(f" [驱动器] stream={stream_id[:8]}, Chatter正在处理，跳过此Tick")
                        continue
                
                # 日志
                if tick.force_dispatch:
                    logger.info(f" [驱动器] stream={stream_id[:8]}, Tick#{tick.tick_count}, 强制分发")
                else:
                    logger.debug(f" [驱动器] stream={stream_id[:8]}, Tick#{tick.tick_count}, 开始处理")
                
                # 更新能量值
                try:
                    await manager._update_stream_energy(stream_id, context)
                except Exception as e:
                    logger.debug(f"更新能量失败: {e}")
                
                # 处理消息
                assert global_config is not None
                try:
                    success = await asyncio.wait_for(
                        manager._process_stream_messages(stream_id, context),
                        global_config.chat.thinking_timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(f" [驱动器] stream={stream_id[:8]}, Tick#{tick.tick_count}, 处理超时")
                    success = False
                
                # 更新统计
                manager.stats["total_process_cycles"] += 1
                if success:
                    logger.debug(f" [驱动器] stream={stream_id[:8]}, Tick#{tick.tick_count}, 处理成功")
                    await asyncio.sleep(0.1)  # 等待清理操作完成
                else:
                    manager.stats["total_failures"] += 1
                    logger.debug(f" [驱动器] stream={stream_id[:8]}, Tick#{tick.tick_count}, 处理失败")
                    
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f" [驱动器] stream={stream_id[:8]}, 处理Tick时出错: {e}")
                manager.stats["total_failures"] += 1
                
    except asyncio.CancelledError:
        logger.info(f" [驱动器] stream={stream_id[:8]}, 任务ID={task_id}, 被取消")
    finally:
        # 清理任务记录
        try:
            context = await manager._get_stream_context(stream_id)
            if context and context.stream_loop_task:
                context.stream_loop_task = None
                logger.debug(f" [驱动器] stream={stream_id[:8]}, 清理任务记录")
        except Exception as e:
            logger.debug(f"清理任务记录失败: {e}")


# ============================================================================
# 流循环管理器
# ============================================================================


class StreamLoopManager:
    """
    流循环管理器 - 基于 Generator + Tick 的事件驱动模式
    
    管理所有聊天流的生命周期，为每个流创建独立的驱动器任务。
    """

    def __init__(self, max_concurrent_streams: int | None = None):
        if global_config is None:
            raise RuntimeError("Global config is not initialized")

        # 统计信息
        self.stats: dict[str, Any] = {
            "active_streams": 0,
            "total_loops": 0,
            "total_process_cycles": 0,
            "total_failures": 0,
            "start_time": time.time(),
        }

        # 配置参数
        self.max_concurrent_streams = max_concurrent_streams or global_config.chat.max_concurrent_distributions

        # 强制分发策略
        self.force_dispatch_unread_threshold: int | None = getattr(
            global_config.chat, "force_dispatch_unread_threshold", 20
        )
        self.force_dispatch_min_interval: float = getattr(global_config.chat, "force_dispatch_min_interval", 0.1)

        # Chatter管理器
        self.chatter_manager: ChatterManager | None = None

        # 状态控制
        self.is_running = False

        # 流启动锁：防止并发启动同一个流的多个任务
        self._stream_start_locks: dict[str, asyncio.Lock] = {}

        logger.info(f"流循环管理器初始化完成 (最大并发流数: {self.max_concurrent_streams})")

    # ========================================================================
    # 生命周期管理
    # ========================================================================

    async def start(self) -> None:
        """启动流循环管理器"""
        if self.is_running:
            logger.warning("流循环管理器已经在运行")
            return
        self.is_running = True
        logger.info("流循环管理器已启动")

    async def stop(self) -> None:
        """停止流循环管理器"""
        if not self.is_running:
            return

        self.is_running = False

        # 取消所有流循环
        try:
            chat_manager = get_chat_manager()
            all_streams = chat_manager.get_all_streams()

            cancel_tasks = []
            for chat_stream in all_streams.values():
                context = chat_stream.context
                if context.stream_loop_task and not context.stream_loop_task.done():
                    context.stream_loop_task.cancel()
                    cancel_tasks.append((chat_stream.stream_id, context.stream_loop_task))

            if cancel_tasks:
                logger.info(f"正在取消 {len(cancel_tasks)} 个流循环任务...")
                await asyncio.gather(
                    *[self._wait_for_task_cancel(stream_id, task) for stream_id, task in cancel_tasks],
                    return_exceptions=True,
                )

            logger.info("所有流循环已清理")
        except Exception as e:
            logger.error(f"停止管理器时出错: {e}")

        logger.info("流循环管理器已停止")

    # ========================================================================
    # 流循环控制
    # ========================================================================

    async def start_stream_loop(self, stream_id: str, force: bool = False) -> bool:
        """
        启动指定流的驱动器任务
        
        Args:
            stream_id: 流ID
            force: 是否强制启动（会先取消现有任务）
            
        Returns:
            bool: 是否成功启动
        """
        # 获取流上下文
        context = await self._get_stream_context(stream_id)
        if not context:
            logger.warning(f"无法获取流上下文: {stream_id}")
            return False

        # 快速路径：如果流已存在且不是强制启动
        if not force and context.stream_loop_task and not context.stream_loop_task.done():
            logger.debug(f" [管理器] stream={stream_id[:8]}, 任务已在运行")
            return True

        # 获取或创建启动锁
        if stream_id not in self._stream_start_locks:
            self._stream_start_locks[stream_id] = asyncio.Lock()
        lock = self._stream_start_locks[stream_id]

        async with lock:
            # 强制启动时先取消旧任务
            if force and context.stream_loop_task and not context.stream_loop_task.done():
                logger.warning(f" [管理器] stream={stream_id[:8]}, 强制启动：取消现有任务")
                old_task = context.stream_loop_task
                old_task.cancel()
                try:
                    await asyncio.wait_for(old_task, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                except Exception as e:
                    logger.warning(f"等待旧任务结束时出错: {e}")

            # 创建新的驱动器任务
            try:
                loop_task = asyncio.create_task(
                    run_chat_stream(stream_id, self),
                    name=f"chat_stream_{stream_id}"
                )
                context.stream_loop_task = loop_task

                self.stats["active_streams"] += 1
                self.stats["total_loops"] += 1

                logger.debug(f" [管理器] stream={stream_id[:8]}, 启动驱动器任务")
                return True

            except Exception as e:
                logger.error(f" [管理器] stream={stream_id[:8]}, 启动失败: {e}")
                return False

    async def stop_stream_loop(self, stream_id: str) -> bool:
        """
        停止指定流的驱动器任务
        
        Args:
            stream_id: 流ID
            
        Returns:
            bool: 是否成功停止
        """
        context = await self._get_stream_context(stream_id)
        if not context:
            return False

        if not context.stream_loop_task or context.stream_loop_task.done():
            return False

        task = context.stream_loop_task
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.error(f"停止任务时出错: {e}")

        context.stream_loop_task = None
        logger.debug(f"停止流循环: {stream_id}")
        return True

    # ========================================================================
    # 内部方法 - 上下文管理
    # ========================================================================

    async def _get_stream_context(self, stream_id: str) -> "StreamContext | None":
        """获取流上下文"""
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if chat_stream:
                return chat_stream.context
            return None
        except Exception as e:
            logger.error(f"获取流上下文失败 {stream_id}: {e}")
            return None

    async def _flush_cached_messages_to_unread(self, stream_id: str) -> list:
        """将缓存消息刷新到未读消息列表"""
        try:
            context = await self._get_stream_context(stream_id)
            if not context:
                return []

            if hasattr(context, "flush_cached_messages"):
                cached_messages = context.flush_cached_messages()
                if cached_messages:
                    logger.debug(f"刷新缓存消息: stream={stream_id[:8]}, 数量={len(cached_messages)}")
                return cached_messages
            return []
        except Exception as e:
            logger.warning(f"刷新缓存失败: {e}")
            return []

    # ========================================================================
    # 内部方法 - 消息处理
    # ========================================================================

    async def _process_stream_messages(self, stream_id: str, context: "StreamContext") -> bool:
        """
        处理流消息
        
        Args:
            stream_id: 流ID
            context: 流上下文
            
        Returns:
            bool: 是否处理成功
        """
        if not self.chatter_manager:
            logger.warning(f"Chatter管理器未设置: {stream_id}")
            return False

        # 二次并发保护
        if context.is_chatter_processing:
            logger.warning(f" [并发保护] stream={stream_id[:8]}, 二次检查触发")
            return False

        self._set_stream_processing_status(stream_id, True)

        chatter_task = None
        try:
            start_time = time.time()
            
            # 检查未读消息
            unread_messages = context.get_unread_messages()
            if not unread_messages:
                logger.debug(f"未读消息为空，跳过处理: {stream_id}")
                return True

            # 静默群组检查
            if await self._should_skip_for_mute_group(stream_id, unread_messages):
                from .message_manager import message_manager
                await message_manager.clear_stream_unread_messages(stream_id)
                logger.debug(f" 静默群组跳过: {stream_id}")
                return True

            logger.debug(f"处理 {len(unread_messages)} 条未读消息: {stream_id}")

            # 设置触发用户ID
            last_message = context.get_last_message()
            if last_message:
                context.triggering_user_id = last_message.user_info.user_id

            # 设置处理标志
            context.is_chatter_processing = True

            # 创建 chatter 任务
            chatter_task = asyncio.create_task(
                self.chatter_manager.process_stream_context(stream_id, context),
                name=f"chatter_{stream_id}"
            )
            context.processing_task = chatter_task

            # 任务完成回调
            def _cleanup(task: asyncio.Task) -> None:
                try:
                    context.processing_task = None
                    if context.is_chatter_processing:
                        context.is_chatter_processing = False
                        self._set_stream_processing_status(stream_id, False)
                except Exception:
                    pass

            chatter_task.add_done_callback(_cleanup)

            # 等待完成
            results = await chatter_task
            success = results.get("success", False)

            if success:
                logger.debug(f"处理成功: {stream_id} (耗时: {time.time() - start_time:.2f}s)")
            else:
                logger.warning(f"处理失败: {stream_id} - {results.get('error_message', '未知错误')}")

            return success
            
        except asyncio.CancelledError:
            if chatter_task and not chatter_task.done():
                chatter_task.cancel()
            raise
        except Exception as e:
            logger.error(f"处理异常: {stream_id} - {e}")
            return False
        finally:
            context.is_chatter_processing = False
            context.processing_task = None
            self._set_stream_processing_status(stream_id, False)

    async def _should_skip_for_mute_group(self, stream_id: str, unread_messages: list) -> bool:
        """检查是否应该因静默群组而跳过处理"""
        if global_config is None:
            return False

        mute_group_list = getattr(global_config.message_receive, "mute_group_list", [])
        if not mute_group_list:
            return False

        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)

            if not chat_stream or not chat_stream.group_info:
                return False

            group_id = str(chat_stream.group_info.group_id)
            if group_id not in mute_group_list:
                return False

            # 检查是否有消息提及 Bot
            bot_name = getattr(global_config.bot, "nickname", "")
            bot_aliases = getattr(global_config.bot, "alias_names", [])
            mention_keywords = [bot_name] + list(bot_aliases) if bot_name else list(bot_aliases)
            mention_keywords = [k for k in mention_keywords if k]

            for msg in unread_messages:
                if getattr(msg, "is_at", False) or getattr(msg, "is_mentioned", False):
                    return False

                content = getattr(msg, "processed_plain_text", "") or getattr(msg, "display_message", "") or ""
                for keyword in mention_keywords:
                    if keyword and keyword in content:
                        return False

            return True

        except Exception as e:
            logger.warning(f"检查静默群组出错: {e}")
            return False

    def _set_stream_processing_status(self, stream_id: str, is_processing: bool) -> None:
        """设置流的处理状态"""
        try:
            from .message_manager import message_manager
            if message_manager.is_running:
                message_manager.set_stream_processing_status(stream_id, is_processing)
        except Exception:
            pass

    def _recover_stale_chatter_state(self, stream_id: str, context: "StreamContext") -> bool:
        """检测并修复 Chatter 处理标志的假死状态"""
        try:
            processing_task = getattr(context, "processing_task", None)

            if processing_task is None:
                context.is_chatter_processing = False
                self._set_stream_processing_status(stream_id, False)
                logger.warning(f" [自愈] stream={stream_id[:8]}, 无任务但标志为真")
                return True

            if processing_task.done():
                context.is_chatter_processing = False
                context.processing_task = None
                self._set_stream_processing_status(stream_id, False)
                logger.warning(f" [自愈] stream={stream_id[:8]}, 任务已结束但标志未清")
                return True

            return False
        except Exception:
            return False

    # ========================================================================
    # 内部方法 - 能量与间隔计算
    # ========================================================================

    async def _update_stream_energy(self, stream_id: str, context: "StreamContext") -> None:
        """更新流的能量值"""
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)

            if not chat_stream:
                return

            assert global_config is not None
            # 合并消息
            all_messages = []
            history_messages = context.get_history_messages(limit=global_config.chat.max_context_size)
            all_messages.extend(history_messages)
            all_messages.extend(context.get_unread_messages())
            all_messages.sort(key=lambda m: m.time)
            messages = all_messages[-global_config.chat.max_context_size:]

            user_id = context.triggering_user_id

            energy = await energy_manager.calculate_focus_energy(
                stream_id=stream_id,
                messages=messages,
                user_id=user_id
            )

            chat_stream._focus_energy = energy
            logger.debug(f"更新能量: {stream_id[:8]} -> {energy:.3f}")

        except Exception as e:
            logger.warning(f"更新能量失败: {e}")

    async def _calculate_interval(self, stream_id: str, has_messages: bool) -> float:
        """计算下次检查间隔"""
        if global_config is None:
            return 5.0

        # 私聊快速响应
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if chat_stream and not chat_stream.group_info:
                return 0.5 if has_messages else 5.0
        except Exception:
            pass

        base_interval = getattr(global_config.chat, "distribution_interval", 5.0)

        if not has_messages:
            return base_interval * 2.0

        # 基于能量计算间隔
        try:
            focus_energy = energy_manager.energy_cache.get(stream_id, (0.5, 0))[0]
            interval = energy_manager.get_distribution_interval(focus_energy)
            return interval
        except Exception:
            return base_interval

    def _needs_force_dispatch_for_context(self, context: "StreamContext", unread_count: int | None = None) -> bool:
        """检查是否需要强制分发"""
        if not self.force_dispatch_unread_threshold or self.force_dispatch_unread_threshold <= 0:
            return False

        if unread_count is None:
            try:
                unread_count = len(context.unread_messages) if context.unread_messages else 0
            except Exception:
                return False

        return unread_count > self.force_dispatch_unread_threshold

    # ========================================================================
    # 辅助方法
    # ========================================================================

    async def _wait_for_task_cancel(self, stream_id: str, task: asyncio.Task) -> None:
        """等待任务取消完成"""
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.error(f"等待任务取消出错: {e}")

    def set_chatter_manager(self, chatter_manager: ChatterManager) -> None:
        """设置 Chatter 管理器"""
        self.chatter_manager = chatter_manager
        logger.debug(f"设置 Chatter 管理器: {chatter_manager.__class__.__name__}")

    # ========================================================================
    # 统计信息
    # ========================================================================

    def get_queue_status(self) -> dict[str, Any]:
        """获取队列状态"""
        current_time = time.time()
        uptime = current_time - self.stats["start_time"] if self.is_running else 0

        return {
            "active_streams": self.stats.get("active_streams", 0),
            "total_loops": self.stats["total_loops"],
            "max_concurrent": self.max_concurrent_streams,
            "is_running": self.is_running,
            "uptime": uptime,
            "total_process_cycles": self.stats["total_process_cycles"],
            "total_failures": self.stats["total_failures"],
            "stats": self.stats.copy(),
        }

    def get_performance_summary(self) -> dict[str, Any]:
        """获取性能摘要"""
        current_time = time.time()
        uptime = current_time - self.stats["start_time"]
        throughput = self.stats["total_process_cycles"] / max(1, uptime / 3600)

        return {
            "uptime_hours": uptime / 3600,
            "active_streams": self.stats.get("active_streams", 0),
            "total_process_cycles": self.stats["total_process_cycles"],
            "total_failures": self.stats["total_failures"],
            "throughput_per_hour": throughput,
            "max_concurrent_streams": self.max_concurrent_streams,
        }


# ============================================================================
# 全局实例
# ============================================================================

stream_loop_manager = StreamLoopManager()

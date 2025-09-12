"""
事件驱动的智能调度器
基于asyncio的精确定时事件调度系统，替代轮询机制
"""

import asyncio
import traceback
from datetime import datetime
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass
from src.common.logger import get_logger

logger = get_logger("event_scheduler")


@dataclass
class ScheduledEvent:
    """调度事件数据类"""
    event_id: str
    trigger_time: datetime
    callback: Callable
    metadata: Dict[str, Any]
    task: Optional[asyncio.Task] = None


class EventDrivenScheduler:
    """事件驱动的调度器"""
    
    def __init__(self):
        self.scheduled_events: Dict[str, ScheduledEvent] = {}
        self._shutdown = False
    
    async def schedule_event(
        self, 
        event_id: str, 
        trigger_time: datetime, 
        callback: Callable,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """
        调度一个事件在指定时间触发
        
        Args:
            event_id: 事件唯一标识
            trigger_time: 触发时间
            callback: 回调函数
            metadata: 事件元数据
            
        Returns:
            bool: 调度成功返回True
        """
        try:
            if metadata is None:
                metadata = {}
                
            # 如果事件已存在，先取消
            if event_id in self.scheduled_events:
                await self.cancel_event(event_id)
            
            # 计算延迟时间
            now = datetime.now()
            delay = (trigger_time - now).total_seconds()
            
            if delay <= 0:
                logger.warning(f"事件 {event_id} 的触发时间已过，立即执行")
                # 立即执行
                asyncio.create_task(self._execute_callback(event_id, callback, metadata))
                return True
            
            # 创建调度事件
            scheduled_event = ScheduledEvent(
                event_id=event_id,
                trigger_time=trigger_time,
                callback=callback,
                metadata=metadata
            )
            
            # 创建异步任务
            scheduled_event.task = asyncio.create_task(
                self._wait_and_execute(scheduled_event)
            )
            
            self.scheduled_events[event_id] = scheduled_event
            logger.info(f"调度事件 {event_id} 将在 {trigger_time} 触发 (延迟 {delay:.1f} 秒)")
            return True
            
        except Exception as e:
            logger.error(f"调度事件失败: {e}")
            return False
    
    async def _wait_and_execute(self, event: ScheduledEvent):
        """等待并执行事件"""
        try:
            now = datetime.now()
            delay = (event.trigger_time - now).total_seconds()
            
            if delay > 0:
                await asyncio.sleep(delay)
            
            # 检查是否被取消
            if self._shutdown or event.event_id not in self.scheduled_events:
                return
                
            # 执行回调
            await self._execute_callback(event.event_id, event.callback, event.metadata)
            
        except asyncio.CancelledError:
            logger.info(f"事件 {event.event_id} 被取消")
        except Exception as e:
            logger.error(f"执行事件 {event.event_id} 时出错: {e}")
        finally:
            # 清理已完成的事件
            if event.event_id in self.scheduled_events:
                del self.scheduled_events[event.event_id]
    
    async def _execute_callback(self, event_id: str, callback: Callable, metadata: Dict[str, Any]):
        """执行回调函数"""
        try:
            logger.info(f"执行调度事件: {event_id}")
            
            # 根据回调函数签名调用
            if asyncio.iscoroutinefunction(callback):
                await callback(metadata)
            else:
                callback(metadata)
                
        except Exception as e:
            logger.error(f"执行回调函数失败: {e}")
            logger.error(traceback.format_exc())
    
    async def cancel_event(self, event_id: str) -> bool:
        """
        取消一个调度事件
        
        Args:
            event_id: 事件ID
            
        Returns:
            bool: 取消成功返回True
        """
        try:
            if event_id in self.scheduled_events:
                event = self.scheduled_events[event_id]
                if event.task and not event.task.done():
                    event.task.cancel()
                del self.scheduled_events[event_id]
                logger.info(f"取消调度事件: {event_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"取消事件失败: {e}")
            return False
    
    async def shutdown(self):
        """关闭调度器，取消所有事件"""
        self._shutdown = True
        for event_id in list(self.scheduled_events.keys()):
            await self.cancel_event(event_id)
        logger.info("事件调度器已关闭")
    
    def get_scheduled_events(self) -> Dict[str, ScheduledEvent]:
        """获取所有调度事件"""
        return self.scheduled_events.copy()
    
    def get_event_count(self) -> int:
        """获取调度事件数量"""
        return len(self.scheduled_events)


# 全局事件调度器实例
event_scheduler = EventDrivenScheduler()


# 便捷函数
async def schedule_reminder(
    reminder_id: str,
    reminder_time: datetime,
    chat_id: str,
    reminder_content: str,
    callback: Callable
):
    """
    调度提醒事件的便捷函数
    
    Args:
        reminder_id: 提醒唯一标识
        reminder_time: 提醒时间
        chat_id: 聊天ID
        reminder_content: 提醒内容
        callback: 回调函数
    """
    metadata = {
        "type": "reminder",
        "chat_id": chat_id,
        "content": reminder_content,
        "created_at": datetime.now().isoformat()
    }
    
    return await event_scheduler.schedule_event(
        event_id=reminder_id,
        trigger_time=reminder_time,
        callback=callback,
        metadata=metadata
    )


async def _execute_reminder_callback(subheartflow_id: str, reminder_text: str, original_message: str = None):
    """执行提醒回调函数"""
    try:
        # 获取对应的subheartflow实例
        from src.chat.heart_flow.heartflow import heartflow
        
        subflow = await heartflow.get_or_create_subheartflow(subheartflow_id)
        if not subflow:
            logger.error(f"无法获取subheartflow实例: {subheartflow_id}")
            return
            
        # 创建主动思考事件，触发完整的思考流程
        from src.chat.chat_loop.proactive.events import ProactiveTriggerEvent
        
        # 使用原始消息来构造reason，如果没有原始消息则使用处理后的内容
        reason_content = original_message if original_message else reminder_text
        
        event = ProactiveTriggerEvent(
            source="reminder_system",
            reason=f"定时提醒：{reason_content}",  # 这里传递完整的原始消息
            metadata={
                "reminder_text": reminder_text,
                "original_message": original_message,
                "trigger_time": datetime.now().isoformat()
            }
        )
        
        # 通过subflow的HeartFChatting实例触发主动思考
        await subflow.heart_fc_instance.proactive_thinker.think(event)
        
        logger.info(f"已触发提醒的主动思考，内容: {reminder_text},没有传递那条消息吗？{original_message}")
        
    except Exception as e:
        logger.error(f"执行提醒回调时发生错误: {e}")
        import traceback
        traceback.print_exc()
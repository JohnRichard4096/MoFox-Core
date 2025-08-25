import asyncio
import time
import traceback
from typing import Optional, TYPE_CHECKING

from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.base.component_types import ChatMode
from .hfc_context import HfcContext

if TYPE_CHECKING:
    from .cycle_processor import CycleProcessor

logger = get_logger("hfc")

class ProactiveThinker:
    def __init__(self, context: HfcContext, cycle_processor: "CycleProcessor"):
        """
        初始化主动思考器
        
        Args:
            context: HFC聊天上下文对象
            cycle_processor: 循环处理器，用于执行主动思考的结果
            
        功能说明:
        - 管理机器人的主动发言功能
        - 根据沉默时间和配置触发主动思考
        - 提供私聊和群聊不同的思考提示模板
        - 使用3-sigma规则计算动态思考间隔
        """
        self.context = context
        self.cycle_processor = cycle_processor
        self._proactive_thinking_task: Optional[asyncio.Task] = None
        
        self.proactive_thinking_prompts = {
            "private": """现在你和你朋友的私聊里面已经隔了{time}没有发送消息了，请你结合上下文以及你和你朋友之前聊过的话题和你的人设来决定要不要主动发送消息，你可以选择：

            1. 继续保持沉默（当{time}以前已经结束了一个话题并且你不想挑起新话题时）
            2. 选择回复（当{time}以前你发送了一条消息且没有人回复你时、你想主动挑起一个话题时）

            请根据当前情况做出选择。如果选择回复，请直接发送你想说的内容；如果选择保持沉默，请只回复"沉默"（注意：这个词不会被发送到群聊中）。""",
            "group": """现在群里面已经隔了{time}没有人发送消息了，请你结合上下文以及群聊里面之前聊过的话题和你的人设来决定要不要主动发送消息，你可以选择：

            1. 继续保持沉默（当{time}以前已经结束了一个话题并且你不想挑起新话题时）
            2. 选择回复（当{time}以前你发送了一条消息且没有人回复你时、你想主动挑起一个话题时）

            请根据当前情况做出选择。如果选择回复，请直接发送你想说的内容；如果选择保持沉默，请只回复"沉默"（注意：这个词不会被发送到群聊中）。""",
        }

    async def start(self):
        """
        启动主动思考器
        
        功能说明:
        - 检查运行状态和配置，避免重复启动
        - 只有在启用主动思考功能时才启动
        - 创建主动思考循环异步任务
        - 设置任务完成回调处理
        - 记录启动日志
        """
        if self.context.running and not self._proactive_thinking_task and global_config.chat.enable_proactive_thinking:
            self._proactive_thinking_task = asyncio.create_task(self._proactive_thinking_loop())
            self._proactive_thinking_task.add_done_callback(self._handle_proactive_thinking_completion)
            logger.info(f"{self.context.log_prefix} 主动思考器已启动")

    async def stop(self):
        """
        停止主动思考器
        
        功能说明:
        - 取消正在运行的主动思考任务
        - 等待任务完全停止
        - 记录停止日志
        """
        if self._proactive_thinking_task and not self._proactive_thinking_task.done():
            self._proactive_thinking_task.cancel()
            await asyncio.sleep(0)
            logger.info(f"{self.context.log_prefix} 主动思考器已停止")

    def _handle_proactive_thinking_completion(self, task: asyncio.Task):
        """
        处理主动思考任务完成
        
        Args:
            task: 完成的异步任务对象
            
        功能说明:
        - 处理任务正常完成或异常情况
        - 记录相应的日志信息
        - 区分取消和异常终止的情况
        """
        try:
            if exception := task.exception():
                logger.error(f"{self.context.log_prefix} 主动思考循环异常: {exception}")
            else:
                logger.info(f"{self.context.log_prefix} 主动思考循环正常结束")
        except asyncio.CancelledError:
            logger.info(f"{self.context.log_prefix} 主动思考循环被取消")

    async def _proactive_thinking_loop(self):
        """
        主动思考的主循环
        
        功能说明:
        - 每15秒检查一次是否需要主动思考
        - 只在FOCUS模式下进行主动思考
        - 检查是否启用主动思考功能
        - 计算沉默时间并与动态间隔比较
        - 达到条件时执行主动思考并更新最后消息时间
        - 处理执行过程中的异常
        """
        while self.context.running:
            await asyncio.sleep(15)

            if self.context.loop_mode != ChatMode.FOCUS:
                continue
            
            if not self._should_enable_proactive_thinking():
                continue

            current_time = time.time()
            silence_duration = current_time - self.context.last_message_time

            target_interval = self._get_dynamic_thinking_interval()
            
            if silence_duration >= target_interval:
                try:
                    await self._execute_proactive_thinking(silence_duration)
                    self.context.last_message_time = current_time
                except Exception as e:
                    logger.error(f"{self.context.log_prefix} 主动思考执行出错: {e}")
                    logger.error(traceback.format_exc())
    
    def _should_enable_proactive_thinking(self) -> bool:
        """
        检查是否应该启用主动思考
        
        Returns:
            bool: 如果应该启用主动思考则返回True
            
        功能说明:
        - 检查聊天流是否存在
        - 检查当前聊天是否在启用列表中（按平台和类型分别检查）
        - 根据聊天类型（群聊/私聊）和配置决定是否启用
        - 群聊需要proactive_thinking_in_group为True
        - 私聊需要proactive_thinking_in_private为True
        """
        if not self.context.chat_stream:
            return False

        is_group_chat = self.context.chat_stream.group_info is not None
        
        # 检查基础开关
        if is_group_chat and not global_config.chat.proactive_thinking_in_group:
            return False
        if not is_group_chat and not global_config.chat.proactive_thinking_in_private:
            return False
        
        # 获取当前聊天的完整标识 (platform:chat_id)
        stream_parts = self.context.stream_id.split(':')
        if len(stream_parts) >= 2:
            platform = stream_parts[0]
            chat_id = stream_parts[1]
            current_chat_identifier = f"{platform}:{chat_id}"
        else:
            # 如果无法解析，则使用原始stream_id
            current_chat_identifier = self.context.stream_id
        
        # 检查是否在启用列表中
        if is_group_chat:
            # 群聊检查
            enable_list = getattr(global_config.chat, 'proactive_thinking_enable_in_groups', [])
            if enable_list and current_chat_identifier not in enable_list:
                return False
        else:
            # 私聊检查  
            enable_list = getattr(global_config.chat, 'proactive_thinking_enable_in_private', [])
            if enable_list and current_chat_identifier not in enable_list:
                return False
            
        return True
    
    def _get_dynamic_thinking_interval(self) -> float:
        """
        获取动态思考间隔
        
        Returns:
            float: 计算得出的思考间隔时间（秒）
            
        功能说明:
        - 使用3-sigma规则计算正态分布的思考间隔
        - 基于base_interval和delta_sigma配置计算
        - 处理特殊情况（为0或负数的配置）
        - 如果timing_utils不可用则使用固定间隔
        - 间隔范围被限制在1秒到86400秒（1天）之间
        """
        try:
            from src.utils.timing_utils import get_normal_distributed_interval
            
            base_interval = global_config.chat.proactive_thinking_interval
            delta_sigma = getattr(global_config.chat, 'delta_sigma', 120)
            
            if base_interval < 0:
                base_interval = abs(base_interval)
            if delta_sigma < 0:
                delta_sigma = abs(delta_sigma)
            
            if base_interval == 0 and delta_sigma == 0:
                return 300
            elif base_interval == 0:
                sigma_percentage = delta_sigma / 1000
                return get_normal_distributed_interval(0, sigma_percentage, 1, 86400, use_3sigma_rule=True)
            elif delta_sigma == 0:
                return base_interval
            
            sigma_percentage = delta_sigma / base_interval
            return get_normal_distributed_interval(base_interval, sigma_percentage, 1, 86400, use_3sigma_rule=True)
            
        except ImportError:
            logger.warning(f"{self.context.log_prefix} timing_utils不可用，使用固定间隔")
            return max(300, abs(global_config.chat.proactive_thinking_interval))
        except Exception as e:
            logger.error(f"{self.context.log_prefix} 动态间隔计算出错: {e}，使用固定间隔")
            return max(300, abs(global_config.chat.proactive_thinking_interval))
    
    def _format_duration(self, seconds: float) -> str:
        """
        格式化持续时间为中文描述
        
        Args:
            seconds: 持续时间（秒）
            
        Returns:
            str: 格式化后的时间字符串，如"1小时30分45秒"
            
        功能说明:
        - 将秒数转换为小时、分钟、秒的组合
        - 只显示非零的时间单位
        - 如果所有单位都为0则显示"0秒"
        - 用于主动思考日志的时间显示
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if hours > 0:
            parts.append(f"{hours}小时")
        if minutes > 0:
            parts.append(f"{minutes}分")
        if secs > 0 or not parts:
            parts.append(f"{secs}秒")

        return "".join(parts)

    async def _execute_proactive_thinking(self, silence_duration: float):
        """
        执行主动思考
        
        Args:
            silence_duration: 沉默持续时间（秒）
        """
        formatted_time = self._format_duration(silence_duration)
        logger.info(f"{self.context.log_prefix} 触发主动思考，已沉默{formatted_time}")

        try:
            # 直接调用 planner 的 PROACTIVE 模式
            action_result_tuple, target_message = await self.cycle_processor.action_planner.plan(mode=ChatMode.PROACTIVE)
            action_result = action_result_tuple.get("action_result")

            # 如果决策不是 do_nothing，则执行
            if action_result and action_result.get("action_type") != "do_nothing":
                logger.info(f"{self.context.log_prefix} 主动思考决策: {action_result.get('action_type')}, 原因: {action_result.get('reasoning')}")
                # 将决策结果交给 cycle_processor 的后续流程处理
                await self.cycle_processor.execute_plan(action_result, target_message)
            else:
                logger.info(f"{self.context.log_prefix} 主动思考决策: 保持沉默")

        except Exception as e:
            logger.error(f"{self.context.log_prefix} 主动思考执行异常: {e}")
            logger.error(traceback.format_exc())

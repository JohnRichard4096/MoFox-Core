"""
Kokoro Flow Chatter 调度器适配器

基于项目统一的 UnifiedScheduler 实现 KFC 的定时任务功能。
不再自己创建后台循环，而是复用全局调度器的基础设施。

核心功能：
1. 会话等待超时检测（短期）
2. 连续思考触发（等待期间的内心活动）
3. 主动思考检测（长期沉默后主动发起对话）
4. 与 UnifiedScheduler 的集成
"""

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.apis.unified_scheduler import (
    TriggerType,
    unified_scheduler,
)

from .models import (
    KokoroSession,
    MentalLogEntry,
    MentalLogEventType,
    SessionStatus,
)
from .session_manager import get_session_manager

if TYPE_CHECKING:
    from .chatter import KokoroFlowChatter

logger = get_logger("kokoro_scheduler_adapter")


class KFCSchedulerAdapter:
    """
    KFC 调度器适配器
    
    使用 UnifiedScheduler 实现 KFC 的定时任务功能，不再自行管理后台循环。
    
    核心功能：
    1. 定期检查处于 WAITING 状态的会话（短期等待超时）
    2. 在特定时间点触发"连续思考"（等待期间内心活动）
    3. 定期检查长期沉默的会话，触发"主动思考"（长期主动发起）
    4. 处理等待超时并触发决策
    """
    
    # 连续思考触发点（等待进度的百分比）
    CONTINUOUS_THINKING_TRIGGERS = [0.3, 0.6, 0.85]
    
    # 任务名称常量
    TASK_NAME_WAITING_CHECK = "kfc_waiting_check"
    TASK_NAME_PROACTIVE_CHECK = "kfc_proactive_check"
    
    # 主动思考检查间隔（5分钟）
    PROACTIVE_CHECK_INTERVAL = 300.0
    
    def __init__(
        self,
        check_interval: float = 10.0,
        on_timeout_callback: Optional[Callable[[KokoroSession], Coroutine[Any, Any, None]]] = None,
        on_continuous_thinking_callback: Optional[Callable[[KokoroSession], Coroutine[Any, Any, None]]] = None,
        on_proactive_thinking_callback: Optional[Callable[[KokoroSession, str], Coroutine[Any, Any, None]]] = None,
    ):
        """
        初始化调度器适配器
        
        Args:
            check_interval: 等待检查间隔（秒）
            on_timeout_callback: 超时回调函数
            on_continuous_thinking_callback: 连续思考回调函数
            on_proactive_thinking_callback: 主动思考回调函数，接收 (session, trigger_reason)
        """
        self.check_interval = check_interval
        self.on_timeout_callback = on_timeout_callback
        self.on_continuous_thinking_callback = on_continuous_thinking_callback
        self.on_proactive_thinking_callback = on_proactive_thinking_callback
        
        self._registered = False
        self._schedule_id: Optional[str] = None
        self._proactive_schedule_id: Optional[str] = None
        
        # 加载主动思考配置
        self._load_proactive_config()
        
        # 统计信息
        self._stats = {
            "total_checks": 0,
            "timeouts_triggered": 0,
            "continuous_thinking_triggered": 0,
            "proactive_thinking_triggered": 0,
            "proactive_checks": 0,
            "last_check_time": 0.0,
        }
        
        logger.info("KFCSchedulerAdapter 初始化完成")
    
    def _load_proactive_config(self) -> None:
        """加载主动思考相关配置"""
        try:
            if global_config and hasattr(global_config, 'kokoro_flow_chatter'):
                proactive_cfg = global_config.kokoro_flow_chatter.proactive_thinking
                self.proactive_enabled = proactive_cfg.enabled
                self.silence_threshold = proactive_cfg.silence_threshold_seconds
                self.min_interval = proactive_cfg.min_interval_between_proactive
                self.min_affinity = getattr(proactive_cfg, 'min_affinity_for_proactive', 0.3)
                self.quiet_hours_start = getattr(proactive_cfg, 'quiet_hours_start', "23:00")
                self.quiet_hours_end = getattr(proactive_cfg, 'quiet_hours_end', "07:00")
            else:
                # 默认值
                self.proactive_enabled = True
                self.silence_threshold = 7200  # 2小时
                self.min_interval = 1800  # 30分钟
                self.min_affinity = 0.3
                self.quiet_hours_start = "23:00"
                self.quiet_hours_end = "07:00"
        except Exception as e:
            logger.warning(f"加载主动思考配置失败，使用默认值: {e}")
            self.proactive_enabled = True
            self.silence_threshold = 7200
            self.min_interval = 1800
            self.min_affinity = 0.3
            self.quiet_hours_start = "23:00"
            self.quiet_hours_end = "07:00"
    
    async def start(self) -> None:
        """启动调度器（注册到 UnifiedScheduler）"""
        if self._registered:
            logger.warning("KFC 调度器已在运行中")
            return
        
        # 注册周期性等待检查任务（每10秒）
        self._schedule_id = await unified_scheduler.create_schedule(
            callback=self._check_waiting_sessions,
            trigger_type=TriggerType.TIME,
            trigger_config={"delay_seconds": self.check_interval},
            is_recurring=True,
            task_name=self.TASK_NAME_WAITING_CHECK,
            force_overwrite=True,
            timeout=30.0,
        )
        
        # 如果启用了主动思考，注册主动思考检查任务（每5分钟）
        if self.proactive_enabled:
            self._proactive_schedule_id = await unified_scheduler.create_schedule(
                callback=self._check_proactive_sessions,
                trigger_type=TriggerType.TIME,
                trigger_config={"delay_seconds": self.PROACTIVE_CHECK_INTERVAL},
                is_recurring=True,
                task_name=self.TASK_NAME_PROACTIVE_CHECK,
                force_overwrite=True,
                timeout=120.0,  # 主动思考可能需要更长时间（涉及 LLM 调用）
            )
            logger.info(f"KFC 主动思考调度已注册: schedule_id={self._proactive_schedule_id}")
        
        self._registered = True
        logger.info(f"KFC 调度器已注册到 UnifiedScheduler: schedule_id={self._schedule_id}")
    
    async def stop(self) -> None:
        """停止调度器（从 UnifiedScheduler 注销）"""
        if not self._registered:
            return
        
        try:
            if self._schedule_id:
                await unified_scheduler.remove_schedule(self._schedule_id)
                logger.info(f"KFC 等待检查调度已注销: schedule_id={self._schedule_id}")
            if self._proactive_schedule_id:
                await unified_scheduler.remove_schedule(self._proactive_schedule_id)
                logger.info(f"KFC 主动思考调度已注销: schedule_id={self._proactive_schedule_id}")
        except Exception as e:
            logger.error(f"停止 KFC 调度器时出错: {e}")
        finally:
            self._registered = False
            self._schedule_id = None
            self._proactive_schedule_id = None
    
    async def _check_waiting_sessions(self) -> None:
        """检查所有等待中的会话（由 UnifiedScheduler 调用）
        
        优化：使用 asyncio.create_task 并行处理多个会话，避免顺序阻塞
        """
        session_manager = get_session_manager()
        waiting_sessions = await session_manager.get_all_waiting_sessions()
        
        self._stats["total_checks"] += 1
        self._stats["last_check_time"] = time.time()
        
        if not waiting_sessions:
            return
        
        # 并行处理所有等待中的会话，避免一个会话阻塞其他会话
        tasks = []
        for session in waiting_sessions:
            task = asyncio.create_task(
                self._safe_process_waiting_session(session),
                name=f"kfc_session_check_{session.user_id}"
            )
            tasks.append(task)
        
        # 等待所有任务完成，但每个任务都有独立的异常处理
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _safe_process_waiting_session(self, session: KokoroSession) -> None:
        """安全地处理等待会话，带有超时保护"""
        try:
            # 给每个会话处理设置 60 秒超时（LLM 调用可能需要较长时间）
            await asyncio.wait_for(
                self._process_waiting_session(session),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.error(f"处理等待会话 {session.user_id} 超时（60秒）")
        except Exception as e:
            logger.error(f"处理等待会话 {session.user_id} 时出错: {e}")
    
    async def _process_waiting_session(self, session: KokoroSession) -> None:
        """
        处理单个等待中的会话
        
        Args:
            session: 等待中的会话
        """
        if session.status != SessionStatus.WAITING:
            return
        
        if session.waiting_since is None:
            return
        
        wait_duration = session.get_waiting_duration()
        max_wait = session.max_wait_seconds
        
        # max_wait_seconds = 0 表示不等待，直接返回 IDLE
        if max_wait <= 0:
            logger.info(f"会话 {session.user_id} 设置为不等待 (max_wait=0)，返回空闲状态")
            session.status = SessionStatus.IDLE
            session.end_waiting()
            session_manager = get_session_manager()
            await session_manager.save_session(session.user_id)
            return
        
        # 检查是否超时
        if session.is_wait_timeout():
            logger.info(f"会话 {session.user_id} 等待超时，触发决策")
            await self._handle_timeout(session)
            return
        
        # 检查是否需要触发连续思考
        wait_progress = wait_duration / max_wait if max_wait > 0 else 0
        
        for trigger_point in self.CONTINUOUS_THINKING_TRIGGERS:
            if self._should_trigger_continuous_thinking(session, wait_progress, trigger_point):
                logger.debug(
                    f"会话 {session.user_id} 触发连续思考 "
                    f"(进度: {wait_progress:.1%}, 触发点: {trigger_point:.1%})"
                )
                await self._handle_continuous_thinking(session, wait_progress)
                break
    
    def _should_trigger_continuous_thinking(
        self,
        session: KokoroSession,
        current_progress: float,
        trigger_point: float,
    ) -> bool:
        """
        判断是否应该触发连续思考
        """
        if current_progress < trigger_point:
            return False
        
        expected_count = sum(
            1 for tp in self.CONTINUOUS_THINKING_TRIGGERS 
            if current_progress >= tp
        )
        
        if session.continuous_thinking_count < expected_count:
            if session.last_continuous_thinking_at is None:
                return True
            
            time_since_last = time.time() - session.last_continuous_thinking_at
            return time_since_last >= 30.0
        
        return False
    
    async def _handle_timeout(self, session: KokoroSession) -> None:
        """
        处理等待超时
        
        Args:
            session: 超时的会话
        """
        self._stats["timeouts_triggered"] += 1
        
        # 更新会话状态
        session.status = SessionStatus.FOLLOW_UP_PENDING
        session.emotional_state.anxiety_level = 0.8
        
        # 添加超时日志
        timeout_entry = MentalLogEntry(
            event_type=MentalLogEventType.TIMEOUT_DECISION,
            timestamp=time.time(),
            thought=f"等了{session.max_wait_seconds}秒了，对方还是没有回复...",
            content="等待超时",
            emotional_snapshot=session.emotional_state.to_dict(),
        )
        session.add_mental_log_entry(timeout_entry)
        
        # 保存会话状态
        session_manager = get_session_manager()
        await session_manager.save_session(session.user_id)
        
        # 调用超时回调
        if self.on_timeout_callback:
            try:
                await self.on_timeout_callback(session)
            except Exception as e:
                logger.error(f"执行超时回调时出错 (user={session.user_id}): {e}")
    
    async def _handle_continuous_thinking(
        self, 
        session: KokoroSession,
        wait_progress: float,
    ) -> None:
        """
        处理连续思考
        
        Args:
            session: 会话
            wait_progress: 等待进度
        """
        self._stats["continuous_thinking_triggered"] += 1
        
        # 更新焦虑程度
        session.emotional_state.update_anxiety_over_time(
            session.get_waiting_duration(),
            session.max_wait_seconds
        )
        
        # 更新连续思考计数
        session.continuous_thinking_count += 1
        session.last_continuous_thinking_at = time.time()
        
        # 生成基于进度的内心想法
        thought = self._generate_waiting_thought(session, wait_progress)
        
        # 添加连续思考日志
        thinking_entry = MentalLogEntry(
            event_type=MentalLogEventType.CONTINUOUS_THINKING,
            timestamp=time.time(),
            thought=thought,
            content="",
            emotional_snapshot=session.emotional_state.to_dict(),
            metadata={"wait_progress": wait_progress},
        )
        session.add_mental_log_entry(thinking_entry)
        
        # 保存会话状态
        session_manager = get_session_manager()
        await session_manager.save_session(session.user_id)
        
        # 调用连续思考回调
        if self.on_continuous_thinking_callback:
            try:
                await self.on_continuous_thinking_callback(session)
            except Exception as e:
                logger.error(f"执行连续思考回调时出错 (user={session.user_id}): {e}")
    
    def _generate_waiting_thought(
        self, 
        session: KokoroSession, 
        wait_progress: float,
    ) -> str:
        """
        生成等待中的内心想法（简单版本，不调用LLM）
        """
        import random
        
        wait_seconds = session.get_waiting_duration()
        wait_minutes = wait_seconds / 60
        
        if wait_progress < 0.4:
            thoughts = [
                f"已经等了{wait_minutes:.1f}分钟了，对方可能在忙吧...",
                f"嗯...{wait_minutes:.1f}分钟过去了，不知道对方在做什么",
                "对方好像还没看到消息，再等等吧",
            ]
        elif wait_progress < 0.7:
            thoughts = [
                f"等了{wait_minutes:.1f}分钟了，有点担心对方是不是不想回了",
                f"{wait_minutes:.1f}分钟了，对方可能真的很忙？",
                "时间过得好慢啊...不知道对方什么时候会回复",
            ]
        else:
            thoughts = [
                f"已经等了{wait_minutes:.1f}分钟了，感觉有点焦虑...",
                f"快{wait_minutes:.0f}分钟了，对方是不是忘记回复了？",
                "等了这么久，要不要主动说点什么呢...",
            ]
        
        return random.choice(thoughts)
    
    # ========================================
    # 主动思考相关方法（长期沉默后主动发起对话）
    # ========================================
    
    async def _check_proactive_sessions(self) -> None:
        """
        检查所有会话是否需要触发主动思考（由 UnifiedScheduler 定期调用）
        
        主动思考的触发条件：
        1. 会话处于 IDLE 状态（不在等待回复中）
        2. 距离上次活动超过 silence_threshold
        3. 距离上次主动思考超过 min_interval
        4. 不在勿扰时段
        5. 与用户的关系亲密度足够
        """
        if not self.proactive_enabled:
            return
        
        # 检查是否在勿扰时段
        if self._is_quiet_hours():
            logger.debug("[KFC] 当前处于勿扰时段，跳过主动思考检查")
            return
        
        self._stats["proactive_checks"] += 1
        
        session_manager = get_session_manager()
        all_sessions = await session_manager.get_all_sessions()
        
        current_time = time.time()
        
        for session in all_sessions:
            try:
                # 检查是否满足主动思考条件（异步获取全局关系分数）
                trigger_reason = await self._should_trigger_proactive(session, current_time)
                if trigger_reason:
                    logger.info(
                        f"[KFC] 触发主动思考: user={session.user_id}, reason={trigger_reason}"
                    )
                    await self._handle_proactive_thinking(session, trigger_reason)
            except Exception as e:
                logger.error(f"检查主动思考条件时出错 (user={session.user_id}): {e}")
    
    def _is_quiet_hours(self) -> bool:
        """
        检查当前是否处于勿扰时段
        
        支持跨午夜的时段（如 23:00 到 07:00）
        """
        try:
            now = datetime.now()
            current_minutes = now.hour * 60 + now.minute
            
            # 解析开始时间
            start_parts = self.quiet_hours_start.split(":")
            start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
            
            # 解析结束时间
            end_parts = self.quiet_hours_end.split(":")
            end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])
            
            # 处理跨午夜的情况
            if start_minutes <= end_minutes:
                # 不跨午夜（如 09:00 到 17:00）
                return start_minutes <= current_minutes < end_minutes
            else:
                # 跨午夜（如 23:00 到 07:00）
                return current_minutes >= start_minutes or current_minutes < end_minutes
                
        except Exception as e:
            logger.warning(f"解析勿扰时段配置失败: {e}")
            return False
    
    async def _should_trigger_proactive(
        self, 
        session: KokoroSession, 
        current_time: float
    ) -> Optional[str]:
        """
        检查是否应该触发主动思考
        
        使用全局关系数据库中的关系分数（而不是 KFC 内部的 emotional_state）
        
        概率机制：关系越亲密，触发概率越高
        - 亲密度 0.3 → 触发概率 10%
        - 亲密度 0.5 → 触发概率 30%
        - 亲密度 0.7 → 触发概率 55%
        - 亲密度 1.0 → 触发概率 90%
        
        Args:
            session: 会话
            current_time: 当前时间戳
            
        Returns:
            触发原因字符串，如果不触发则返回 None
        """
        import random
        
        # 条件1：必须处于 IDLE 状态
        if session.status != SessionStatus.IDLE:
            return None
        
        # 条件2：距离上次活动超过沉默阈值
        silence_duration = current_time - session.last_activity_at
        if silence_duration < self.silence_threshold:
            return None
        
        # 条件3：距离上次主动思考超过最小间隔
        if session.last_proactive_at is not None:
            time_since_last_proactive = current_time - session.last_proactive_at
            if time_since_last_proactive < self.min_interval:
                return None
        
        # 条件4：从数据库获取全局关系分数
        relationship_score = await self._get_global_relationship_score(session.user_id)
        if relationship_score < self.min_affinity:
            logger.debug(
                f"主动思考跳过（关系分数不足）: user={session.user_id}, "
                f"score={relationship_score:.2f}, min={self.min_affinity:.2f}"
            )
            return None
        
        # 条件5：基于关系分数的概率判断
        # 公式：probability = 0.1 + 0.8 * ((score - min_affinity) / (1.0 - min_affinity))^1.5
        # 这样分数从 min_affinity 到 1.0 映射到概率 10% 到 90%
        # 使用1.5次幂让曲线更陡峭，高亲密度时概率增长更快
        normalized_score = (relationship_score - self.min_affinity) / (1.0 - self.min_affinity)
        probability = 0.1 + 0.8 * (normalized_score ** 1.5)
        probability = min(probability, 0.9)  # 最高90%，永远不是100%确定
        
        if random.random() > probability:
            # 这次检查没触发，但记录一下（用于调试）
            logger.debug(
                f"主动思考概率检查未通过: user={session.user_id}, "
                f"score={relationship_score:.2f}, probability={probability:.1%}"
            )
            return None
        
        # 所有条件满足，生成触发原因
        silence_hours = silence_duration / 3600
        logger.info(
            f"主动思考触发: user={session.user_id}, "
            f"silence={silence_hours:.1f}h, score={relationship_score:.2f}, prob={probability:.1%}"
        )
        return f"沉默了{silence_hours:.1f}小时，想主动关心一下对方"
    
    async def _get_global_relationship_score(self, user_id: str) -> float:
        """
        从全局关系数据库获取关系分数
        
        Args:
            user_id: 用户ID
            
        Returns:
            关系分数 (0.0-1.0)，如果没有记录返回默认值 0.3
        """
        try:
            from src.common.database.api.specialized import get_user_relationship
            
            # 从 user_id 解析 platform（格式通常是 "platform_userid"）
            # 这里假设 user_id 中包含 platform 信息，需要根据实际情况调整
            # 先尝试直接查询，如果失败再用默认值
            relationship = await get_user_relationship(
                platform="qq",  # TODO: 从 session 或 stream_id 获取真实 platform
                user_id=user_id,
                target_id="bot",
            )
            
            if relationship and hasattr(relationship, 'relationship_score'):
                return relationship.relationship_score
            
            # 没有找到关系记录，返回默认值
            return 0.3
            
        except Exception as e:
            logger.warning(f"获取全局关系分数失败 (user={user_id}): {e}")
            return 0.3  # 出错时返回较低的默认值
    
    async def _handle_proactive_thinking(
        self, 
        session: KokoroSession, 
        trigger_reason: str
    ) -> None:
        """
        处理主动思考
        
        Args:
            session: 会话
            trigger_reason: 触发原因
        """
        self._stats["proactive_thinking_triggered"] += 1
        
        # 更新会话状态
        session.last_proactive_at = time.time()
        session.proactive_count += 1
        
        # 添加主动思考日志
        proactive_entry = MentalLogEntry(
            event_type=MentalLogEventType.PROACTIVE_THINKING,
            timestamp=time.time(),
            thought=trigger_reason,
            content="主动思考触发",
            emotional_snapshot=session.emotional_state.to_dict(),
            metadata={"trigger_reason": trigger_reason},
        )
        session.add_mental_log_entry(proactive_entry)
        
        # 保存会话状态
        session_manager = get_session_manager()
        await session_manager.save_session(session.user_id)
        
        # 调用主动思考回调（由 chatter 处理实际的 LLM 调用和动作执行）
        if self.on_proactive_thinking_callback:
            try:
                await self.on_proactive_thinking_callback(session, trigger_reason)
            except Exception as e:
                logger.error(f"执行主动思考回调时出错 (user={session.user_id}): {e}")
    
    def set_timeout_callback(
        self,
        callback: Callable[[KokoroSession], Coroutine[Any, Any, None]],
    ) -> None:
        """设置超时回调函数"""
        self.on_timeout_callback = callback
    
    def set_continuous_thinking_callback(
        self,
        callback: Callable[[KokoroSession], Coroutine[Any, Any, None]],
    ) -> None:
        """设置连续思考回调函数"""
        self.on_continuous_thinking_callback = callback
    
    def set_proactive_thinking_callback(
        self,
        callback: Callable[[KokoroSession, str], Coroutine[Any, Any, None]],
    ) -> None:
        """设置主动思考回调函数"""
        self.on_proactive_thinking_callback = callback
    
    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "is_running": self._registered,
            "check_interval": self.check_interval,
        }
    
    @property
    def is_running(self) -> bool:
        """调度器是否正在运行"""
        return self._registered


# 全局适配器实例
_scheduler_adapter: Optional[KFCSchedulerAdapter] = None


def get_scheduler() -> KFCSchedulerAdapter:
    """获取全局调度器适配器实例"""
    global _scheduler_adapter
    if _scheduler_adapter is None:
        _scheduler_adapter = KFCSchedulerAdapter()
    return _scheduler_adapter


async def initialize_scheduler(
    check_interval: float = 10.0,
    on_timeout_callback: Optional[Callable[[KokoroSession], Coroutine[Any, Any, None]]] = None,
    on_continuous_thinking_callback: Optional[Callable[[KokoroSession], Coroutine[Any, Any, None]]] = None,
    on_proactive_thinking_callback: Optional[Callable[[KokoroSession, str], Coroutine[Any, Any, None]]] = None,
) -> KFCSchedulerAdapter:
    """
    初始化并启动调度器
    
    Args:
        check_interval: 检查间隔
        on_timeout_callback: 超时回调
        on_continuous_thinking_callback: 连续思考回调
        on_proactive_thinking_callback: 主动思考回调
        
    Returns:
        KFCSchedulerAdapter: 调度器适配器实例
    """
    global _scheduler_adapter
    _scheduler_adapter = KFCSchedulerAdapter(
        check_interval=check_interval,
        on_timeout_callback=on_timeout_callback,
        on_continuous_thinking_callback=on_continuous_thinking_callback,
        on_proactive_thinking_callback=on_proactive_thinking_callback,
    )
    await _scheduler_adapter.start()
    return _scheduler_adapter


async def shutdown_scheduler() -> None:
    """关闭调度器"""
    global _scheduler_adapter
    if _scheduler_adapter:
        await _scheduler_adapter.stop()
        _scheduler_adapter = None

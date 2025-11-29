"""
Kokoro Flow Chatter 会话管理器

负责管理用户会话的完整生命周期：
- 创建、加载、保存会话
- 会话状态持久化
- 会话清理和维护
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from src.common.logger import get_logger

from .models import (
    EmotionalState,
    KokoroSession,
    MentalLogEntry,
    MentalLogEventType,
    SessionStatus,
)

logger = get_logger("kokoro_session_manager")


class SessionManager:
    """
    Kokoro Flow Chatter 会话管理器
    
    单例模式实现，为每个私聊用户维护独立的会话
    
    Features:
    - 会话的创建、获取、更新和删除
    - 自动持久化到JSON文件
    - 会话过期清理
    - 线程安全的并发访问
    """
    
    _instance: Optional["SessionManager"] = None
    _lock = asyncio.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        data_dir: str = "data/kokoro_flow_chatter/sessions",
        max_session_age_days: int = 30,
        auto_save_interval: int = 300,
    ):
        """
        初始化会话管理器
        
        Args:
            data_dir: 会话数据存储目录
            max_session_age_days: 会话最大保留天数
            auto_save_interval: 自动保存间隔（秒）
        """
        # 避免重复初始化
        if hasattr(self, "_initialized") and self._initialized:
            return
        
        self._initialized = True
        self.data_dir = Path(data_dir)
        self.max_session_age_days = max_session_age_days
        self.auto_save_interval = auto_save_interval
        
        # 内存中的会话缓存
        self._sessions: dict[str, KokoroSession] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        
        # 后台任务
        self._auto_save_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        
        # 确保数据目录存在
        self._ensure_data_dir()
        
        logger.info(f"SessionManager 初始化完成，数据目录: {self.data_dir}")
    
    def _ensure_data_dir(self) -> None:
        """确保数据目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_session_file_path(self, user_id: str) -> Path:
        """获取会话文件路径"""
        # 清理user_id中的特殊字符
        safe_user_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
        return self.data_dir / f"{safe_user_id}.json"
    
    async def _get_session_lock(self, user_id: str) -> asyncio.Lock:
        """获取会话级别的锁"""
        if user_id not in self._session_locks:
            self._session_locks[user_id] = asyncio.Lock()
        return self._session_locks[user_id]
    
    async def start(self) -> None:
        """启动会话管理器的后台任务"""
        if self._running:
            return
        
        self._running = True
        
        # 启动自动保存任务
        self._auto_save_task = asyncio.create_task(self._auto_save_loop())
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info("SessionManager 后台任务已启动")
    
    async def stop(self) -> None:
        """停止会话管理器并保存所有会话"""
        self._running = False
        
        # 取消后台任务
        if self._auto_save_task:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # 保存所有会话
        await self.save_all_sessions()
        
        logger.info("SessionManager 已停止，所有会话已保存")
    
    async def _auto_save_loop(self) -> None:
        """自动保存循环"""
        while self._running:
            try:
                await asyncio.sleep(self.auto_save_interval)
                await self.save_all_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"自动保存会话时出错: {e}")
    
    async def _cleanup_loop(self) -> None:
        """清理过期会话循环"""
        while self._running:
            try:
                # 每小时清理一次
                await asyncio.sleep(3600)
                await self.cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理过期会话时出错: {e}")
    
    async def get_session(self, user_id: str, stream_id: str) -> KokoroSession:
        """
        获取或创建用户会话
        
        Args:
            user_id: 用户ID
            stream_id: 聊天流ID
            
        Returns:
            KokoroSession: 用户会话对象
        """
        lock = await self._get_session_lock(user_id)
        async with lock:
            # 检查内存缓存
            if user_id in self._sessions:
                session = self._sessions[user_id]
                # 更新stream_id（可能发生变化）
                session.stream_id = stream_id
                return session
            
            # 尝试从文件加载
            session = await self._load_session_from_file(user_id)
            if session:
                session.stream_id = stream_id
                self._sessions[user_id] = session
                logger.debug(f"从文件加载会话: {user_id}")
                return session
            
            # 创建新会话
            session = KokoroSession(
                user_id=user_id,
                stream_id=stream_id,
                status=SessionStatus.IDLE,
                emotional_state=EmotionalState(),
                mental_log=[],
            )
            
            # 添加初始日志条目
            initial_entry = MentalLogEntry(
                event_type=MentalLogEventType.STATE_CHANGE,
                timestamp=time.time(),
                thought="与这位用户的对话开始了，我对接下来的交流充满期待。",
                content="会话创建",
                emotional_snapshot=session.emotional_state.to_dict(),
            )
            session.add_mental_log_entry(initial_entry)
            
            self._sessions[user_id] = session
            logger.info(f"创建新会话: {user_id}")
            
            return session
    
    async def _load_session_from_file(self, user_id: str) -> Optional[KokoroSession]:
        """从文件加载会话"""
        file_path = self._get_session_file_path(user_id)
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            session = KokoroSession.from_dict(data)
            logger.debug(f"成功从文件加载会话: {user_id}")
            return session
            
        except json.JSONDecodeError as e:
            logger.error(f"解析会话文件失败 {user_id}: {e}")
            # 备份损坏的文件
            backup_path = file_path.with_suffix(".json.bak")
            os.rename(file_path, backup_path)
            return None
        except Exception as e:
            logger.error(f"加载会话文件失败 {user_id}: {e}")
            return None
    
    async def save_session(self, user_id: str) -> bool:
        """
        保存单个会话到文件
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否保存成功
        """
        lock = await self._get_session_lock(user_id)
        async with lock:
            if user_id not in self._sessions:
                return False
            
            session = self._sessions[user_id]
            file_path = self._get_session_file_path(user_id)
            
            try:
                data = session.to_dict()
                
                # 先写入临时文件，再重命名（原子操作）
                temp_path = file_path.with_suffix(".json.tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                os.replace(temp_path, file_path)
                logger.debug(f"保存会话成功: {user_id}")
                return True
                
            except Exception as e:
                logger.error(f"保存会话失败 {user_id}: {e}")
                return False
    
    async def save_all_sessions(self) -> int:
        """
        保存所有会话
        
        Returns:
            int: 成功保存的会话数量
        """
        saved_count = 0
        for user_id in list(self._sessions.keys()):
            if await self.save_session(user_id):
                saved_count += 1
        
        if saved_count > 0:
            logger.debug(f"批量保存完成，共保存 {saved_count} 个会话")
        
        return saved_count
    
    async def update_session(
        self,
        user_id: str,
        status: Optional[SessionStatus] = None,
        emotional_state: Optional[EmotionalState] = None,
        mental_log_entry: Optional[MentalLogEntry] = None,
        **kwargs,
    ) -> bool:
        """
        更新会话状态
        
        Args:
            user_id: 用户ID
            status: 新的会话状态
            emotional_state: 新的情感状态
            mental_log_entry: 要添加的心理日志条目
            **kwargs: 其他要更新的字段
            
        Returns:
            bool: 是否更新成功
        """
        lock = await self._get_session_lock(user_id)
        async with lock:
            if user_id not in self._sessions:
                return False
            
            session = self._sessions[user_id]
            
            if status is not None:
                old_status = session.status
                session.status = status
                logger.debug(f"会话状态变更 {user_id}: {old_status} -> {status}")
            
            if emotional_state is not None:
                session.emotional_state = emotional_state
            
            if mental_log_entry is not None:
                session.add_mental_log_entry(mental_log_entry)
            
            # 更新其他字段
            for key, value in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, value)
            
            session.last_activity_at = time.time()
            
            return True
    
    async def delete_session(self, user_id: str) -> bool:
        """
        删除会话
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否删除成功
        """
        lock = await self._get_session_lock(user_id)
        async with lock:
            # 从内存中删除
            if user_id in self._sessions:
                del self._sessions[user_id]
            
            # 从文件系统删除
            file_path = self._get_session_file_path(user_id)
            if file_path.exists():
                try:
                    os.remove(file_path)
                    logger.info(f"删除会话: {user_id}")
                    return True
                except Exception as e:
                    logger.error(f"删除会话文件失败 {user_id}: {e}")
                    return False
            
            return True
    
    async def cleanup_expired_sessions(self) -> int:
        """
        清理过期会话
        
        Returns:
            int: 清理的会话数量
        """
        cleaned_count = 0
        current_time = time.time()
        max_age_seconds = self.max_session_age_days * 24 * 3600
        
        # 检查文件系统中的所有会话
        for file_path in self.data_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                last_activity = data.get("last_activity_at", 0)
                if current_time - last_activity > max_age_seconds:
                    user_id = data.get("user_id", file_path.stem)
                    
                    # 从内存中删除
                    if user_id in self._sessions:
                        del self._sessions[user_id]
                    
                    # 删除文件
                    os.remove(file_path)
                    cleaned_count += 1
                    logger.info(f"清理过期会话: {user_id}")
                    
            except Exception as e:
                logger.error(f"清理会话时出错 {file_path}: {e}")
        
        if cleaned_count > 0:
            logger.info(f"共清理 {cleaned_count} 个过期会话")
        
        return cleaned_count
    
    async def get_all_waiting_sessions(self) -> list[KokoroSession]:
        """
        获取所有处于等待状态的会话
        
        Returns:
            list[KokoroSession]: 等待中的会话列表
        """
        waiting_sessions = []
        
        for session in self._sessions.values():
            if session.status == SessionStatus.WAITING:
                waiting_sessions.append(session)
        
        return waiting_sessions
    
    async def get_all_sessions(self) -> list[KokoroSession]:
        """
        获取所有内存中的会话
        
        用于主动思考检查等需要遍历所有会话的场景
        
        Returns:
            list[KokoroSession]: 所有会话列表
        """
        return list(self._sessions.values())
    
    async def get_session_statistics(self) -> dict:
        """
        获取会话统计信息
        
        Returns:
            dict: 统计信息字典
        """
        total_in_memory = len(self._sessions)
        status_counts = {}
        
        for session in self._sessions.values():
            status = str(session.status)
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # 统计文件系统中的会话
        total_on_disk = len(list(self.data_dir.glob("*.json")))
        
        return {
            "total_in_memory": total_in_memory,
            "total_on_disk": total_on_disk,
            "status_counts": status_counts,
            "data_directory": str(self.data_dir),
        }
    
    def get_session_sync(self, user_id: str) -> Optional[KokoroSession]:
        """
        同步获取会话（仅从内存缓存）
        
        Args:
            user_id: 用户ID
            
        Returns:
            Optional[KokoroSession]: 会话对象，如果不存在返回None
        """
        return self._sessions.get(user_id)


# 全局会话管理器实例
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取全局会话管理器实例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


async def initialize_session_manager(
    data_dir: str = "data/kokoro_flow_chatter/sessions",
    **kwargs,
) -> SessionManager:
    """
    初始化并启动会话管理器
    
    Args:
        data_dir: 数据存储目录
        **kwargs: 其他配置参数
        
    Returns:
        SessionManager: 会话管理器实例
    """
    global _session_manager
    _session_manager = SessionManager(data_dir=data_dir, **kwargs)
    await _session_manager.start()
    return _session_manager

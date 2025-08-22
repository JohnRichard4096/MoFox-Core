# -*- coding: utf-8 -*-
"""
异步瞬时记忆包装器
提供对现有瞬时记忆系统的异步包装，支持超时控制和回退机制
"""

import asyncio
import time
from typing import Optional, List, Dict, Any
from src.common.logger import get_logger
from src.config.config import global_config

logger = get_logger("async_instant_memory_wrapper")

class AsyncInstantMemoryWrapper:
    """异步瞬时记忆包装器"""
    
    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        self.llm_memory = None
        self.vector_memory = None
        self.cache: Dict[str, tuple[Any, float]] = {}  # 缓存：(结果, 时间戳)
        self.cache_ttl = 300  # 缓存5分钟
        self.default_timeout = 3.0  # 默认超时3秒

        # 从配置中读取是否启用各种记忆系统
        self.llm_memory_enabled = global_config.memory.enable_llm_instant_memory
        self.vector_memory_enabled = global_config.memory.enable_vector_instant_memory

    async def _ensure_llm_memory(self):
        """确保LLM记忆系统已初始化"""
        if self.llm_memory is None and self.llm_memory_enabled:
            try:
                from src.chat.memory_system.instant_memory import InstantMemory
                self.llm_memory = InstantMemory(self.chat_id)
                logger.info(f"LLM瞬时记忆系统已初始化: {self.chat_id}")
            except Exception as e:
                logger.warning(f"LLM瞬时记忆系统初始化失败: {e}")
                self.llm_memory_enabled = False  # 初始化失败则禁用

    async def _ensure_vector_memory(self):
        """确保向量记忆系统已初始化"""
        if self.vector_memory is None and self.vector_memory_enabled:
            try:
                from src.chat.memory_system.vector_instant_memory import VectorInstantMemoryV2
                self.vector_memory = VectorInstantMemoryV2(self.chat_id)
                logger.info(f"向量瞬时记忆系统已初始化: {self.chat_id}")
            except Exception as e:
                logger.warning(f"向量瞬时记忆系统初始化失败: {e}")
                self.vector_memory_enabled = False # 初始化失败则禁用
    
    def _get_cache_key(self, operation: str, content: str) -> str:
        """生成缓存键"""
        return f"{operation}_{self.chat_id}_{hash(content)}"
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """检查缓存是否有效"""
        if cache_key not in self.cache:
            return False
        
        _, timestamp = self.cache[cache_key]
        return time.time() - timestamp < self.cache_ttl
    
    def _get_cached_result(self, cache_key: str) -> Optional[Any]:
        """获取缓存结果"""
        if self._is_cache_valid(cache_key):
            result, _ = self.cache[cache_key]
            return result
        return None
    
    def _cache_result(self, cache_key: str, result: Any):
        """缓存结果"""
        self.cache[cache_key] = (result, time.time())
    
    async def store_memory_async(self, content: str, timeout: Optional[float] = None) -> bool:
        """异步存储记忆（带超时控制）"""
        if timeout is None:
            timeout = self.default_timeout
        
        success_count = 0
        
        # 异步存储到LLM记忆系统
        await self._ensure_llm_memory()
        if self.llm_memory:
            try:
                await asyncio.wait_for(
                    self.llm_memory.create_and_store_memory(content),
                    timeout=timeout
                )
                success_count += 1
                logger.debug(f"LLM记忆存储成功: {content[:50]}...")
            except asyncio.TimeoutError:
                logger.warning(f"LLM记忆存储超时: {content[:50]}...")
            except Exception as e:
                logger.error(f"LLM记忆存储失败: {e}")
        
        # 异步存储到向量记忆系统
        await self._ensure_vector_memory()
        if self.vector_memory:
            try:
                await asyncio.wait_for(
                    self.vector_memory.store_message(content),
                    timeout=timeout
                )
                success_count += 1
                logger.debug(f"向量记忆存储成功: {content[:50]}...")
            except asyncio.TimeoutError:
                logger.warning(f"向量记忆存储超时: {content[:50]}...")
            except Exception as e:
                logger.error(f"向量记忆存储失败: {e}")
        
        return success_count > 0
    
    async def retrieve_memory_async(self, query: str, timeout: Optional[float] = None,
                                   use_cache: bool = True) -> Optional[Any]:
        """异步检索记忆（带缓存和超时控制）"""
        if timeout is None:
            timeout = self.default_timeout
        
        # 检查缓存
        if use_cache:
            cache_key = self._get_cache_key("retrieve", query)
            cached_result = self._get_cached_result(cache_key)
            if cached_result is not None:
                logger.debug(f"记忆检索命中缓存: {query[:30]}...")
                return cached_result
        
        # 尝试多种记忆系统
        results = []
        
        # 从向量记忆系统检索（优先，速度快）
        await self._ensure_vector_memory()
        if self.vector_memory:
            try:
                vector_result = await asyncio.wait_for(
                    self.vector_memory.get_memory_for_context(query),
                    timeout=timeout * 0.6  # 给向量系统60%的时间
                )
                if vector_result:
                    results.append(vector_result)
                    logger.debug(f"向量记忆检索成功: {query[:30]}...")
            except asyncio.TimeoutError:
                logger.warning(f"向量记忆检索超时: {query[:30]}...")
            except Exception as e:
                logger.error(f"向量记忆检索失败: {e}")
        
        # 从LLM记忆系统检索（备用，更准确但较慢）
        await self._ensure_llm_memory()
        if self.llm_memory and len(results) == 0:  # 只有向量检索失败时才使用LLM
            try:
                llm_result = await asyncio.wait_for(
                    self.llm_memory.get_memory(query),
                    timeout=timeout * 0.4  # 给LLM系统40%的时间
                )
                if llm_result:
                    results.extend(llm_result)
                    logger.debug(f"LLM记忆检索成功: {query[:30]}...")
            except asyncio.TimeoutError:
                logger.warning(f"LLM记忆检索超时: {query[:30]}...")
            except Exception as e:
                logger.error(f"LLM记忆检索失败: {e}")
        
        # 合并结果
        final_result = None
        if results:
            if len(results) == 1:
                final_result = results[0]
            else:
                # 合并多个结果
                if isinstance(results[0], str):
                    final_result = "\n".join(str(r) for r in results)
                elif isinstance(results[0], list):
                    final_result = []
                    for r in results:
                        if isinstance(r, list):
                            final_result.extend(r)
                        else:
                            final_result.append(r)
                else:
                    final_result = results[0]  # 使用第一个结果
        
        # 缓存结果
        if use_cache and final_result is not None:
            cache_key = self._get_cache_key("retrieve", query)
            self._cache_result(cache_key, final_result)
        
        return final_result
    
    async def get_memory_with_fallback(self, query: str, max_timeout: float = 2.0) -> str:
        """获取记忆的回退方法，保证不会长时间阻塞"""
        try:
            # 首先尝试快速检索
            result = await self.retrieve_memory_async(query, timeout=max_timeout)
            
            if result:
                if isinstance(result, list):
                    return "\n".join(str(item) for item in result)
                return str(result)
            
            return ""
            
        except Exception as e:
            logger.error(f"记忆检索完全失败: {e}")
            return ""
    
    def store_memory_background(self, content: str):
        """在后台存储记忆（发后即忘模式）"""
        async def background_store():
            try:
                await self.store_memory_async(content, timeout=10.0)  # 后台任务可以用更长超时
            except Exception as e:
                logger.error(f"后台记忆存储失败: {e}")
        
        # 创建后台任务
        asyncio.create_task(background_store())
    
    def get_status(self) -> Dict[str, Any]:
        """获取包装器状态"""
        return {
            "chat_id": self.chat_id,
            "llm_memory_available": self.llm_memory is not None,
            "vector_memory_available": self.vector_memory is not None,
            "cache_entries": len(self.cache),
            "cache_ttl": self.cache_ttl,
            "default_timeout": self.default_timeout
        }
    
    def clear_cache(self):
        """清理缓存"""
        self.cache.clear()
        logger.info(f"记忆缓存已清理: {self.chat_id}")

# 缓存包装器实例，避免重复创建
_wrapper_cache: Dict[str, AsyncInstantMemoryWrapper] = {}

def get_async_instant_memory(chat_id: str) -> AsyncInstantMemoryWrapper:
    """获取异步瞬时记忆包装器实例"""
    if chat_id not in _wrapper_cache:
        _wrapper_cache[chat_id] = AsyncInstantMemoryWrapper(chat_id)
    return _wrapper_cache[chat_id]

def clear_wrapper_cache():
    """清理包装器缓存"""
    global _wrapper_cache
    _wrapper_cache.clear()
    logger.info("异步瞬时记忆包装器缓存已清理")

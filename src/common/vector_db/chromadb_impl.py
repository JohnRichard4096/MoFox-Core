import threading
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

from .base import VectorDBBase
from src.common.logger import get_logger

logger = get_logger("chromadb_impl")

class ChromaDBImpl(VectorDBBase):
    """
    ChromaDB 的具体实现，遵循 VectorDBBase 接口。
    采用单例模式，确保全局只有一个 ChromaDB 客户端实例。
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(ChromaDBImpl, cls).__new__(cls)
        return cls._instance

    def __init__(self, path: str = "data/chroma_db", **kwargs: Any):
        """
        初始化 ChromaDB 客户端。
        由于是单例，这个初始化只会执行一次。
        """
        if not hasattr(self, '_initialized'):
            with self._lock:
                if not hasattr(self, '_initialized'):
                    try:
                        self.client = chromadb.PersistentClient(
                            path=path,
                            settings=Settings(anonymized_telemetry=False)
                        )
                        self._collections: Dict[str, Any] = {}
                        self._initialized = True
                        logger.info(f"ChromaDB 客户端已初始化，数据库路径: {path}")
                    except Exception as e:
                        logger.error(f"ChromaDB 初始化失败: {e}")
                        self.client = None
                        self._initialized = False

    def get_or_create_collection(self, name: str, **kwargs: Any) -> Any:
        if not self.client:
            raise ConnectionError("ChromaDB 客户端未初始化")
            
        if name in self._collections:
            return self._collections[name]
        
        try:
            collection = self.client.get_or_create_collection(name=name, **kwargs)
            self._collections[name] = collection
            logger.info(f"成功获取或创建集合: '{name}'")
            return collection
        except Exception as e:
            logger.error(f"获取或创建集合 '{name}' 失败: {e}")
            return None

    def add(
        self,
        collection_name: str,
        embeddings: List[List[float]],
        documents: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> None:
        collection = self.get_or_create_collection(collection_name)
        if collection:
            try:
                collection.add(
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids,
                )
            except Exception as e:
                logger.error(f"向集合 '{collection_name}' 添加数据失败: {e}")

    def query(
        self,
        collection_name: str,
        query_embeddings: List[List[float]],
        n_results: int = 1,
        where: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, List[Any]]:
        collection = self.get_or_create_collection(collection_name)
        if collection:
            try:
                query_params = {
                    "query_embeddings": query_embeddings,
                    "n_results": n_results,
                    **kwargs,
                }
                if where:
                    query_params["where"] = where
                return collection.query(**query_params)
            except Exception as e:
                logger.error(f"查询集合 '{collection_name}' 失败: {e}")
        return {}

    def get(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        where_document: Optional[Dict[str, Any]] = None,
        include: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """根据条件从集合中获取数据"""
        collection = self.get_or_create_collection(collection_name)
        if collection:
            try:
                return collection.get(
                    ids=ids,
                    where=where,
                    limit=limit,
                    offset=offset,
                    where_document=where_document,
                    include=include,
                )
            except Exception as e:
                logger.error(f"从集合 '{collection_name}' 获取数据失败: {e}")
        return {}

    def delete(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> None:
        collection = self.get_or_create_collection(collection_name)
        if collection:
            try:
                collection.delete(ids=ids, where=where)
            except Exception as e:
                logger.error(f"从集合 '{collection_name}' 删除数据失败: {e}")

    def count(self, collection_name: str) -> int:
        collection = self.get_or_create_collection(collection_name)
        if collection:
            try:
                return collection.count()
            except Exception as e:
                logger.error(f"获取集合 '{collection_name}' 计数失败: {e}")
        return 0
        
    def delete_collection(self, name: str) -> None:
        if not self.client:
            raise ConnectionError("ChromaDB 客户端未初始化")
        
        try:
            self.client.delete_collection(name=name)
            if name in self._collections:
                del self._collections[name]
            logger.info(f"集合 '{name}' 已被删除")
        except Exception as e:
            logger.error(f"删除集合 '{name}' 失败: {e}")
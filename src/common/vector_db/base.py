from abc import ABC, abstractmethod
from typing import Any


class VectorDBBase(ABC):
    """
    向量数据库的抽象基类 (ABC)，定义了所有向量数据库实现必须遵循的接口。
    """

    @abstractmethod
    def __init__(self, path: str, **kwargs: Any):
        """
        初始化向量数据库客户端。

        Args:
            path (str): 数据库文件的存储路径。
            **kwargs: 其他特定于实现的参数。
        """
        pass

    @abstractmethod
    def get_or_create_collection(self, name: str, **kwargs: Any) -> Any:
        """
        获取或创建一个集合 (Collection)。

        Args:
            name (str): 集合的名称。
            **kwargs: 其他特定于实现的参数 (例如 metadata)。

        Returns:
            Any: 代表集合的对象。
        """
        pass

    @abstractmethod
    def add(
        self,
        collection_name: str,
        embeddings: list[list[float]],
        documents: list[str] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """
        向指定集合中添加数据。

        Args:
            collection_name (str): 目标集合的名称。
            embeddings (List[List[float]]): 向量列表。
            documents (Optional[List[str]], optional): 文档列表。Defaults to None.
            metadatas (Optional[List[Dict[str, Any]]], optional): 元数据列表。Defaults to None.
            ids (Optional[List[str]], optional): ID 列表。Defaults to None.
        """
        pass

    @abstractmethod
    def query(
        self,
        collection_name: str,
        query_embeddings: list[list[float]],
        n_results: int = 1,
        where: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, list[Any]]:
        """
        在指定集合中查询相似向量。

        Args:
            collection_name (str): 目标集合的名称。
            query_embeddings (List[List[float]]): 用于查询的向量列表。
            n_results (int, optional): 返回结果的数量。Defaults to 1.
            where (Optional[Dict[str, Any]], optional): 元数据过滤条件。Defaults to None.
            **kwargs: 其他特定于实现的参数。

        Returns:
            Dict[str, List[Any]]: 查询结果，通常包含 ids, distances, metadatas, documents。
        """
        pass

    @abstractmethod
    def delete(
        self,
        collection_name: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> None:
        """
        从指定集合中删除数据。

        Args:
            collection_name (str): 目标集合的名称。
            ids (Optional[List[str]], optional): 要删除的条目的 ID 列表。Defaults to None.
            where (Optional[Dict[str, Any]], optional): 基于元数据的过滤条件。Defaults to None.
        """
        pass

    @abstractmethod
    def get(
        self,
        collection_name: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        where_document: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        根据条件从集合中获取数据。

        Args:
            collection_name (str): 目标集合的名称。
            ids (Optional[List[str]], optional): 要获取的条目的 ID 列表。Defaults to None.
            where (Optional[Dict[str, Any]], optional): 基于元数据的过滤条件。Defaults to None.
            limit (Optional[int], optional): 返回结果的数量限制。Defaults to None.
            offset (Optional[int], optional): 返回结果的偏移量。Defaults to None.
            where_document (Optional[Dict[str, Any]], optional): 基于文档内容的过滤条件。Defaults to None.
            include (Optional[List[str]], optional): 指定返回的数据字段 (e.g., ["metadatas", "documents"])。Defaults to None.

        Returns:
            Dict[str, Any]: 获取到的数据。
        """
        pass

    @abstractmethod
    def count(self, collection_name: str) -> int:
        """
        获取指定集合中的条目总数。

        Args:
            collection_name (str): 目标集合的名称。

        Returns:
            int: 条目总数。
        """
        pass

    @abstractmethod
    def delete_collection(self, name: str) -> None:
        """
        删除一个集合。

        Args:
            name (str): 要删除的集合的名称。
        """
        pass

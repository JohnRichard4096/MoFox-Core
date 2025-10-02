from .base import VectorDBBase
from .chromadb_impl import ChromaDBImpl


def get_vector_db_service() -> VectorDBBase:
    """
    工厂函数，初始化并返回向量数据库服务实例。

    目前硬编码为 ChromaDB，未来可以从配置中读取。
    """
    # TODO: 从全局配置中读取数据库类型和路径
    db_path = "data/chroma_db"

    # ChromaDBImpl 是一个单例，所以这里每次调用都会返回同一个实例
    return ChromaDBImpl(path=db_path)


# 全局向量数据库服务实例
vector_db_service: VectorDBBase = get_vector_db_service()

__all__ = ["VectorDBBase", "vector_db_service"]

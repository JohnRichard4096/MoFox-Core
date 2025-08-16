"""数据库API模块

提供数据库操作相关功能，采用标准Python包设计模式
使用方式：
    from src.plugin_system.apis import database_api
    records = await database_api.db_query(ActionRecords, query_type="get")
    record = await database_api.db_save(ActionRecords, data={"action_id": "123"})

注意：此模块现在使用SQLAlchemy实现，提供更好的连接管理和错误处理
"""

from src.common.database.sqlalchemy_database_api import (
    db_query,
    db_save,
    db_get,
    store_action_info,
    MODEL_MAPPING
)

# 保持向后兼容性
__all__ = [
    'db_query',
    'db_save',
    'db_get',
    'store_action_info',
    'MODEL_MAPPING'
]

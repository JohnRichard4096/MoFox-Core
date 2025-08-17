# 数据库自动迁移模块 (`db_migration.py`) 设计文档

## 1. 目标

创建一个自动化的数据库迁移模块，用于在应用启动时检查数据库结构，并自动进行以下修复：

1.  **创建缺失的表**：如果代码模型中定义的表在数据库中不存在，则自动创建。
2.  **添加缺失的列**：如果数据库中的某个表现有的列比代码模型中定义的少，则自动添加缺失的列。

## 2. 实现思路

我们将使用 SQLAlchemy 的 `Inspector` 来获取数据库的元数据（即实际的表和列信息），并将其与 `SQLAlchemy` 模型（`Base.metadata`）中定义的结构进行比较。

核心逻辑分为以下几个步骤：

1.  **获取数据库引擎**：从现有代码中获取已初始化的 SQLAlchemy 引擎实例。
2.  **获取 Inspector**：通过引擎创建一个 `Inspector` 对象。
3.  **获取所有模型**：遍历 `Base.metadata.tables`，获取所有在代码中定义的表模型。
4.  **获取数据库中所有表名**：使用 `inspector.get_table_names()` 获取数据库中实际存在的所有表名。
5.  **创建缺失的表**：通过比较模型表名和数据库表名，找出所有缺失的表，并使用 `table.create(engine)` 来创建它们。
6.  **检查并添加缺失的列**：
    *   遍历每一个代码中定义的表模型。
    *   使用 `inspector.get_columns(table_name)` 获取数据库中该表的实际列。
    *   比较模型列和实际列，找出所有缺失的列。
    *   对于每一个缺失的列，生成一个 `ALTER TABLE ... ADD COLUMN ...` 的 SQL 语句，并执行它。

## 3. 伪代码实现

```python
# mmc/src/common/database/db_migration.py

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from src.common.database.sqlalchemy_models import Base, get_engine
from src.common.logger import get_logger

logger = get_logger("db_migration")

def check_and_migrate_database():
    """
    检查数据库结构并自动迁移（添加缺失的表和列）。
    """
    logger.info("正在检查数据库结构并执行自动迁移...")
    engine = get_engine()
    inspector = inspect(engine)

    # 1. 获取数据库中所有已存在的表名
    db_table_names = set(inspector.get_table_names())

    # 2. 遍历所有在代码中定义的模型
    for table_name, table in Base.metadata.tables.items():
        logger.debug(f"正在检查表: {table_name}")

        # 3. 如果表不存在，则创建它
        if table_name not in db_table_names:
            logger.info(f"表 '{table_name}' 不存在，正在创建...")
            try:
                table.create(engine)
                logger.info(f"表 '{table_name}' 创建成功。")
            except Exception as e:
                logger.error(f"创建表 '{table_name}' 失败: {e}")
            continue

        # 4. 如果表已存在，则检查并添加缺失的列
        db_columns = {col['name'] for col in inspector.get_columns(table_name)}
        model_columns = {col.name for col in table.c}

        missing_columns = model_columns - db_columns
        if not missing_columns:
            logger.debug(f"表 '{table_name}' 结构一致，无需修改。")
            continue
            
        logger.info(f"在表 '{table_name}' 中发现缺失的列: {', '.join(missing_columns)}")
        with engine.connect() as connection:
            for column_name in missing_columns:
                column = table.c[column_name]
                
                # 构造并执行 ALTER TABLE 语句
                # 注意：这里的实现需要考虑不同数据库（SQLite, MySQL）的语法差异
                # 为了简化，我们先使用一个通用的格式，后续可以根据需要进行扩展
                try:
                    column_type = column.type.compile(engine.dialect)
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                    
                    # 可以在这里添加对默认值、非空约束等的处理
                    
                    connection.execute(text(sql))
                    logger.info(f"成功向表 '{table_name}' 添加列 '{column_name}'。")
                except Exception as e:
                    logger.error(f"向表 '{table_name}' 添加列 '{column_name}' 失败: {e}")
            
            # 提交事务
            if connection.in_transaction():
                connection.commit()

    logger.info("数据库结构检查与自动迁移完成。")

```

## 4. 集成到启动流程

为了让这个迁移模块在应用启动时自动运行，我们需要在 `mmc/src/common/database/sqlalchemy_models.py` 的 `initialize_database` 函数中调用它。

修改后的 `initialize_database` 函数将如下所示：

```python
# mmc/src/common/database/sqlalchemy_models.py

# ... (其他 import)
from src.common.database.db_migration import check_and_migrate_database # 导入新函数

# ... (代码)

def initialize_database():
    """初始化数据库引擎和会话"""
    global _engine, _SessionLocal

    if _engine is not None:
        return _engine, _SessionLocal

    # ... (数据库连接和引擎创建逻辑)

    _engine = create_engine(database_url, **engine_kwargs)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # 在这里，我们不再直接调用 create_all
    # Base.metadata.create_all(bind=_engine)
    
    # 而是调用新的迁移函数，它会处理表的创建和列的添加
    check_and_migrate_database()

    logger.info(f"SQLAlchemy数据库初始化成功: {config.database_type}")
    return _engine, _SessionLocal

# ... (其他代码)
```

通过这样的修改，我们就可以在不改变现有初始化流程入口的情况下，无缝地集成自动化的数据库结构检查和修复功能。
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
        db_columns = {col["name"] for col in inspector.get_columns(table_name)}
        model_columns = {col.name for col in table.c}

        missing_columns = model_columns - db_columns
        if not missing_columns:
            logger.debug(f"表 '{table_name}' 结构一致，无需修改。")
            continue

        logger.info(f"在表 '{table_name}' 中发现缺失的列: {', '.join(missing_columns)}")
        with engine.connect() as connection:
            trans = connection.begin()
            try:
                for column_name in missing_columns:
                    column = table.c[column_name]

                    # 构造并执行 ALTER TABLE 语句
                    try:
                        column_type = column.type.compile(engine.dialect)
                        sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"

                        # 添加默认值和非空约束的处理
                        if column.default is not None:
                            default_value = column.default.arg
                            if isinstance(default_value, str):
                                sql += f" DEFAULT '{default_value}'"
                            else:
                                sql += f" DEFAULT {default_value}"

                        if not column.nullable:
                            sql += " NOT NULL"

                        connection.execute(text(sql))
                        logger.info(f"成功向表 '{table_name}' 添加列 '{column_name}'。")
                    except Exception as e:
                        logger.error(f"向表 '{table_name}' 添加列 '{column_name}' 失败: {e}")

                trans.commit()
            except Exception as e:
                logger.error(f"在表 '{table_name}' 添加列时发生错误，事务已回滚: {e}")
                trans.rollback()

    logger.info("数据库结构检查与自动迁移完成。")

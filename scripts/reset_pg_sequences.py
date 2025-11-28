#!/usr/bin/env python3
"""重置 PostgreSQL 序列值

迁移数据后，PostgreSQL 的序列（用于自增主键）可能没有更新到正确的值，
导致插入新记录时出现主键冲突。此脚本会自动检测并重置所有序列。

使用方法:
    python scripts/reset_pg_sequences.py --host localhost --port 5432 --database maibot --user postgres --password your_password
"""

import argparse
import psycopg


def reset_sequences(host: str, port: int, database: str, user: str, password: str):
    """重置所有序列值"""
    conn_str = f"host={host} port={port} dbname={database} user={user} password={password}"
    
    print(f"连接到 PostgreSQL: {host}:{port}/{database}")
    conn = psycopg.connect(conn_str)
    conn.autocommit = True
    
    # 查询所有序列及其关联的表和列
    query = """
    SELECT 
        t.relname AS table_name,
        a.attname AS column_name,
        s.relname AS sequence_name
    FROM pg_class s
    JOIN pg_depend d ON d.objid = s.oid
    JOIN pg_class t ON d.refobjid = t.oid
    JOIN pg_attribute a ON (d.refobjid, d.refobjsubid) = (a.attrelid, a.attnum)
    WHERE s.relkind = 'S'
    """
    
    cursor = conn.execute(query)
    sequences = cursor.fetchall()
    
    print(f"发现 {len(sequences)} 个序列")
    
    reset_count = 0
    for table_name, col_name, seq_name in sequences:
        try:
            # 获取当前最大 ID
            max_result = conn.execute(f'SELECT MAX("{col_name}") FROM "{table_name}"')
            max_id = max_result.fetchone()[0]
            
            if max_id is not None:
                # 重置序列
                conn.execute(f"SELECT setval('{seq_name}', {max_id}, true)")
                print(f"  ✓ {seq_name} -> {max_id}")
                reset_count += 1
            else:
                print(f"  - {seq_name}: 表为空，跳过")
                
        except Exception as e:
            print(f"  ✗ {table_name}.{col_name}: {e}")
    
    conn.close()
    print(f"\n✅ 重置完成！共重置 {reset_count} 个序列")


def main():
    parser = argparse.ArgumentParser(description="重置 PostgreSQL 序列值")
    parser.add_argument("--host", default="localhost", help="PostgreSQL 主机")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL 端口")
    parser.add_argument("--database", default="maibot", help="数据库名")
    parser.add_argument("--user", default="postgres", help="用户名")
    parser.add_argument("--password", required=True, help="密码")
    
    args = parser.parse_args()
    
    reset_sequences(args.host, args.port, args.database, args.user, args.password)


if __name__ == "__main__":
    main()

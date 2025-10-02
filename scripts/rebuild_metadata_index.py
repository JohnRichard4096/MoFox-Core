#!/usr/bin/env python
"""
从现有ChromaDB数据重建JSON元数据索引
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.chat.memory_system.memory_metadata_index import MemoryMetadataIndexEntry
from src.chat.memory_system.memory_system import MemorySystem
from src.common.logger import get_logger

logger = get_logger(__name__)


async def rebuild_metadata_index():
    """从ChromaDB重建元数据索引"""
    print("=" * 80)
    print("重建JSON元数据索引")
    print("=" * 80)

    # 初始化记忆系统
    print("\n🔧 初始化记忆系统...")
    ms = MemorySystem()
    await ms.initialize()
    print("✅ 记忆系统已初始化")

    if not hasattr(ms.unified_storage, "metadata_index"):
        print("❌ 元数据索引管理器未初始化")
        return

    # 获取所有记忆
    print("\n📥 从ChromaDB获取所有记忆...")
    from src.common.vector_db import vector_db_service

    try:
        # 获取集合中的所有记忆ID
        collection_name = ms.unified_storage.config.memory_collection
        result = vector_db_service.get(
            collection_name=collection_name, include=["documents", "metadatas", "embeddings"]
        )

        if not result or not result.get("ids"):
            print("❌ ChromaDB中没有找到记忆数据")
            return

        ids = result["ids"]
        metadatas = result.get("metadatas", [])

        print(f"✅ 找到 {len(ids)} 条记忆")

        # 重建元数据索引
        print("\n🔨 开始重建元数据索引...")
        entries = []
        success_count = 0

        for i, (memory_id, metadata) in enumerate(zip(ids, metadatas, strict=False), 1):
            try:
                # 从ChromaDB元数据重建索引条目
                import orjson

                entry = MemoryMetadataIndexEntry(
                    memory_id=memory_id,
                    user_id=metadata.get("user_id", "unknown"),
                    memory_type=metadata.get("memory_type", "general"),
                    subjects=orjson.loads(metadata.get("subjects", "[]")),
                    objects=[metadata.get("object")] if metadata.get("object") else [],
                    keywords=orjson.loads(metadata.get("keywords", "[]")),
                    tags=orjson.loads(metadata.get("tags", "[]")),
                    importance=2,  # 默认NORMAL
                    confidence=2,  # 默认MEDIUM
                    created_at=metadata.get("created_at", 0.0),
                    access_count=metadata.get("access_count", 0),
                    chat_id=metadata.get("chat_id"),
                    content_preview=None,
                )

                # 尝试解析importance和confidence的枚举名称
                if "importance" in metadata:
                    imp_str = metadata["importance"]
                    if imp_str == "LOW":
                        entry.importance = 1
                    elif imp_str == "NORMAL":
                        entry.importance = 2
                    elif imp_str == "HIGH":
                        entry.importance = 3
                    elif imp_str == "CRITICAL":
                        entry.importance = 4

                if "confidence" in metadata:
                    conf_str = metadata["confidence"]
                    if conf_str == "LOW":
                        entry.confidence = 1
                    elif conf_str == "MEDIUM":
                        entry.confidence = 2
                    elif conf_str == "HIGH":
                        entry.confidence = 3
                    elif conf_str == "VERIFIED":
                        entry.confidence = 4

                entries.append(entry)
                success_count += 1

                if i % 100 == 0:
                    print(f"  处理进度: {i}/{len(ids)} ({success_count} 成功)")

            except Exception as e:
                logger.warning(f"处理记忆 {memory_id} 失败: {e}")
                continue

        print(f"\n✅ 成功解析 {success_count}/{len(ids)} 条记忆元数据")

        # 批量更新索引
        print("\n💾 保存元数据索引...")
        ms.unified_storage.metadata_index.batch_add_or_update(entries)
        ms.unified_storage.metadata_index.save()

        # 显示统计信息
        stats = ms.unified_storage.metadata_index.get_stats()
        print("\n📊 重建后的索引统计:")
        print(f"  - 总记忆数: {stats['total_memories']}")
        print(f"  - 主语数量: {stats['subjects_count']}")
        print(f"  - 关键词数量: {stats['keywords_count']}")
        print(f"  - 标签数量: {stats['tags_count']}")
        print("  - 类型分布:")
        for mtype, count in stats["types"].items():
            print(f"    - {mtype}: {count}")

        print("\n✅ 元数据索引重建完成！")

    except Exception as e:
        logger.error(f"重建索引失败: {e}", exc_info=True)
        print(f"❌ 重建索引失败: {e}")


if __name__ == "__main__":
    asyncio.run(rebuild_metadata_index())

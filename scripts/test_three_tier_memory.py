"""
三层记忆系统测试脚本
用于验证系统各组件是否正常工作
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def test_perceptual_memory():
    """测试感知记忆层"""
    print("\n" + "=" * 60)
    print("测试1: 感知记忆层")
    print("=" * 60)

    from src.memory_graph.three_tier.perceptual_manager import get_perceptual_manager

    manager = get_perceptual_manager()
    await manager.initialize()

    # 添加测试消息
    test_messages = [
        ("user1", "今天天气真好", 1700000000.0),
        ("user2", "是啊，适合出去玩", 1700000001.0),
        ("user1", "我们去公园吧", 1700000002.0),
        ("user2", "好主意！", 1700000003.0),
        ("user1", "带上野餐垫", 1700000004.0),
    ]

    for sender, content, timestamp in test_messages:
        message = {
            "message_id": f"msg_{timestamp}",
            "sender": sender,
            "content": content,
            "timestamp": timestamp,
            "platform": "test",
            "stream_id": "test_stream",
        }
        await manager.add_message(message)

    print(f"✅ 成功添加 {len(test_messages)} 条消息")

    # 测试TopK召回
    results = await manager.recall_blocks("公园野餐", top_k=2)
    print(f"✅ TopK召回返回 {len(results)} 个块")

    if results:
        print(f"   第一个块包含 {len(results[0].messages)} 条消息")

    # 获取统计信息
    stats = manager.get_statistics()  # 不是async方法
    print(f"✅ 统计信息: {stats}")

    return True


async def test_short_term_memory():
    """测试短期记忆层"""
    print("\n" + "=" * 60)
    print("测试2: 短期记忆层")
    print("=" * 60)

    from src.memory_graph.three_tier.models import MemoryBlock
    from src.memory_graph.three_tier.short_term_manager import get_short_term_manager

    manager = get_short_term_manager()
    await manager.initialize()

    # 创建测试块
    test_block = MemoryBlock(
        id="test_block_1",
        messages=[
            {
                "message_id": "msg1",
                "sender": "user1",
                "content": "我明天要参加一个重要的面试",
                "timestamp": 1700000000.0,
                "platform": "test",
            }
        ],
        combined_text="我明天要参加一个重要的面试",
        recall_count=3,
    )

    # 从感知块转换为短期记忆
    try:
        await manager.add_from_block(test_block)
        print("✅ 成功将感知块转换为短期记忆")
    except Exception as e:
        print(f"⚠️ 转换失败（可能需要LLM）: {e}")
        return False

    # 测试搜索
    results = await manager.search_memories("面试", top_k=3)
    print(f"✅ 搜索返回 {len(results)} 条记忆")

    # 获取统计
    stats = manager.get_statistics()
    print(f"✅ 统计信息: {stats}")

    return True


async def test_long_term_memory():
    """测试长期记忆层"""
    print("\n" + "=" * 60)
    print("测试3: 长期记忆层")
    print("=" * 60)

    from src.memory_graph.three_tier.long_term_manager import get_long_term_manager

    manager = get_long_term_manager()
    await manager.initialize()

    print("✅ 长期记忆管理器初始化成功")
    print("   （需要现有记忆图系统支持）")

    # 获取统计
    stats = manager.get_statistics()
    print(f"✅ 统计信息: {stats}")

    return True


async def test_unified_manager():
    """测试统一管理器"""
    print("\n" + "=" * 60)
    print("测试4: 统一管理器")
    print("=" * 60)

    from src.memory_graph.three_tier.unified_manager import UnifiedMemoryManager

    manager = UnifiedMemoryManager()
    await manager.initialize()

    # 添加测试消息
    message = {
        "message_id": "unified_test_1",
        "sender": "user1",
        "content": "这是一条测试消息",
        "timestamp": 1700000000.0,
        "platform": "test",
        "stream_id": "test_stream",
    }
    await manager.add_message(message)

    print("✅ 通过统一接口添加消息成功")

    # 测试搜索
    results = await manager.search_memories("测试")
    print(f"✅ 统一搜索返回结果:")
    print(f"   感知块: {len(results.get('perceptual_blocks', []))}")
    print(f"   短期记忆: {len(results.get('short_term_memories', []))}")
    print(f"   长期记忆: {len(results.get('long_term_memories', []))}")

    # 获取统计
    stats = manager.get_statistics()  # 不是async方法
    print(f"✅ 综合统计:")
    print(f"   感知层: {stats.get('perceptual', {})}")
    print(f"   短期层: {stats.get('short_term', {})}")
    print(f"   长期层: {stats.get('long_term', {})}")

    return True


async def test_configuration():
    """测试配置加载"""
    print("\n" + "=" * 60)
    print("测试5: 配置系统")
    print("=" * 60)

    from src.config.config import global_config

    if not hasattr(global_config, "three_tier_memory"):
        print("❌ 配置类中未找到 three_tier_memory 字段")
        return False

    config = global_config.three_tier_memory

    if config is None:
        print("⚠️ 三层记忆配置为 None（可能未在 bot_config.toml 中配置）")
        print("   请在 bot_config.toml 中添加 [three_tier_memory] 配置")
        return False

    print(f"✅ 配置加载成功")
    print(f"   启用状态: {config.enable}")
    print(f"   数据目录: {config.data_dir}")
    print(f"   感知层最大块数: {config.perceptual_max_blocks}")
    print(f"   短期层最大记忆数: {config.short_term_max_memories}")
    print(f"   激活阈值: {config.activation_threshold}")

    return True


async def test_integration():
    """测试系统集成"""
    print("\n" + "=" * 60)
    print("测试6: 系统集成")
    print("=" * 60)

    # 首先需要确保配置启用
    from src.config.config import global_config

    if not global_config.three_tier_memory or not global_config.three_tier_memory.enable:
        print("⚠️ 配置未启用，跳过集成测试")
        return False

    # 测试单例模式
    from src.memory_graph.three_tier.manager_singleton import (
        get_unified_memory_manager,
        initialize_unified_memory_manager,
    )

    # 初始化
    await initialize_unified_memory_manager()
    manager = get_unified_memory_manager()

    if manager is None:
        print("❌ 统一管理器初始化失败")
        return False

    print("✅ 单例模式正常工作")

    # 测试多次获取
    manager2 = get_unified_memory_manager()
    if manager is not manager2:
        print("❌ 单例模式失败（返回不同实例）")
        return False

    print("✅ 单例一致性验证通过")

    return True


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "🔬" * 30)
    print("三层记忆系统集成测试")
    print("🔬" * 30)

    tests = [
        ("配置系统", test_configuration),
        ("感知记忆层", test_perceptual_memory),
        ("短期记忆层", test_short_term_memory),
        ("长期记忆层", test_long_term_memory),
        ("统一管理器", test_unified_manager),
        ("系统集成", test_integration),
    ]

    results = []

    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ 测试 {name} 失败: {e}")
            import traceback

            traceback.print_exc()
            results.append((name, False))

    # 打印测试总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n🎉 所有测试通过！三层记忆系统工作正常。")
    else:
        print("\n⚠️ 部分测试失败，请查看上方详细信息。")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

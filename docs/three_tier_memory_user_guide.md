# 三层记忆系统使用指南

## 📋 概述

三层记忆系统是一个受人脑记忆机制启发的增强型记忆管理系统，包含三个层次：

1. **感知记忆层 (Perceptual Memory)**: 短期缓冲，存储最近的消息块
2. **短期记忆层 (Short-Term Memory)**: 活跃记忆，存储结构化的重要信息
3. **长期记忆层 (Long-Term Memory)**: 持久记忆，基于图谱的知识库

## 🚀 快速启动

### 1. 启用系统

编辑 `config/bot_config.toml`，添加或修改以下配置：

```toml
[three_tier_memory]
enable = true  # 启用三层记忆系统
data_dir = "data/memory_graph/three_tier"  # 数据存储目录
```

### 2. 配置参数

#### 感知记忆层配置
```toml
perceptual_max_blocks = 50  # 最大存储块数
perceptual_block_size = 5   # 每个块包含的消息数
perceptual_similarity_threshold = 0.55  # 相似度阈值（0-1）
perceptual_topk = 3  # TopK召回数量
```

#### 短期记忆层配置
```toml
short_term_max_memories = 100  # 最大短期记忆数量
short_term_transfer_threshold = 0.6  # 转移到长期的重要性阈值
short_term_search_top_k = 5  # 搜索时返回的最大数量
short_term_decay_factor = 0.98  # 衰减因子（每次访问）
activation_threshold = 3  # 激活阈值（感知→短期）
```

#### 长期记忆层配置
```toml
long_term_batch_size = 10  # 批量转移大小
long_term_decay_factor = 0.95  # 衰减因子（比短期慢）
long_term_auto_transfer_interval = 600  # 自动转移间隔（秒）
```

#### Judge模型配置
```toml
judge_model_name = "utils_small"  # 用于决策的LLM模型
judge_temperature = 0.1  # Judge模型的温度参数
enable_judge_retrieval = true  # 启用智能检索判断
```

### 3. 启动机器人

```powershell
python bot.py
```

系统会自动：
- 初始化三层记忆管理器
- 创建必要的数据目录
- 启动自动转移任务（每10分钟一次）

## 🔍 工作流程

### 消息处理流程

```
新消息到达
    ↓
添加到感知记忆 (消息块)
    ↓
累积到5条消息 → 生成向量
    ↓
被TopK召回3次 → 激活
    ↓
激活块转移到短期记忆
    ↓
LLM提取结构化信息 (主语/话题/宾语)
    ↓
LLM决策合并/更新/新建/丢弃
    ↓
重要性 ≥ 0.6 → 转移到长期记忆
    ↓
LLM生成图操作 (CREATE/UPDATE/MERGE节点/边)
    ↓
更新记忆图谱
```

### 检索流程

```
用户查询
    ↓
检索感知记忆 (TopK相似块)
    ↓
检索短期记忆 (TopK结构化记忆)
    ↓
Judge模型评估充分性
    ↓
不充分 → 检索长期记忆图谱
    ↓
合并结果返回
```

## 💡 使用示例

### 场景1: 日常对话

**用户**: "我今天去了超市买了牛奶和面包"

**系统处理**:
1. 添加到感知记忆块
2. 累积5条消息后生成向量
3. 如果被召回3次，转移到短期记忆
4. LLM提取: `主语=用户, 话题=购物, 宾语=牛奶和面包`
5. 重要性评分 < 0.6，暂留短期

### 场景2: 重要事件

**用户**: "下周三我要参加一个重要的面试"

**系统处理**:
1. 感知记忆 → 短期记忆（激活）
2. LLM提取: `主语=用户, 话题=面试, 宾语=下周三`
3. 重要性评分 ≥ 0.6（涉及未来计划）
4. 转移到长期记忆
5. 生成图操作:
   ```json
   {
     "operation": "CREATE_MEMORY",
     "content": "用户将在下周三参加重要面试"
   }
   ```

### 场景3: 智能检索

**查询**: "我上次说的面试是什么时候？"

**检索流程**:
1. 检索感知记忆: 找到最近提到"面试"的消息块
2. 检索短期记忆: 找到结构化的面试相关记忆
3. Judge模型判断: "需要更多上下文"
4. 检索长期记忆: 找到"下周三的面试"事件
5. 返回综合结果: 
   - 感知层: 最近的对话片段
   - 短期层: 面试的结构化信息
   - 长期层: 完整的面试计划详情

## 🛠️ 运维管理

### 查看统计信息

```python
from src.memory_graph.three_tier.manager_singleton import get_unified_memory_manager

manager = get_unified_memory_manager()
stats = await manager.get_statistics()

print(f"感知记忆块数: {stats['perceptual']['total_blocks']}")
print(f"短期记忆数: {stats['short_term']['total_memories']}")
print(f"长期记忆数: {stats['long_term']['total_memories']}")
```

### 手动触发转移

```python
# 短期 → 长期
transferred = await manager.transfer_to_long_term()
print(f"转移了 {transferred} 条记忆到长期")
```

### 清理过期记忆

```python
# 系统会自动衰减，但可以手动清理低重要性记忆
from src.memory_graph.three_tier.short_term_manager import get_short_term_manager

short_term = get_short_term_manager()
await short_term.cleanup_low_importance(threshold=0.2)
```

## 🎯 最佳实践

### 1. 模型选择

- **Judge模型**: 推荐使用快速小模型 (utils_small, gpt-4o-mini)
- **提取模型**: 需要较强的理解能力 (gpt-4, claude-3.5-sonnet)
- **图操作模型**: 需要逻辑推理能力 (gpt-4, claude)

### 2. 参数调优

**高频对话场景** (群聊):
```toml
perceptual_max_blocks = 100  # 增加缓冲
activation_threshold = 5      # 提高激活门槛
short_term_max_memories = 200 # 增加容量
```

**低频深度对话** (私聊):
```toml
perceptual_max_blocks = 30
activation_threshold = 2
short_term_transfer_threshold = 0.5  # 更容易转移到长期
```

### 3. 性能优化

- **批量处理**: 长期转移使用批量模式（默认10条/批）
- **缓存策略**: Judge决策结果会缓存，避免重复调用
- **异步执行**: 所有操作都是异步的，不阻塞主流程

### 4. 数据安全

- **定期备份**: `data/memory_graph/three_tier/` 目录
- **JSON持久化**: 所有数据以JSON格式存储
- **崩溃恢复**: 系统会自动从最后保存的状态恢复

## 🐛 故障排除

### 问题1: 系统未初始化

**症状**: 日志显示 "三层记忆系统未启用"

**解决**:
1. 检查 `bot_config.toml` 中 `[three_tier_memory] enable = true`
2. 确认配置文件路径正确
3. 重启机器人

### 问题2: LLM调用失败

**症状**: "LLM决策失败" 错误

**解决**:
1. 检查模型配置 (`model_config.toml`)
2. 确认API密钥有效
3. 尝试更换为其他模型
4. 查看日志中的详细错误信息

### 问题3: 记忆未正确转移

**症状**: 短期记忆一直增长，长期记忆没有更新

**解决**:
1. 降低 `short_term_transfer_threshold`
2. 检查自动转移任务是否运行
3. 手动触发转移测试
4. 查看LLM生成的图操作是否正确

### 问题4: 检索结果不准确

**症状**: 检索到的记忆不相关

**解决**:
1. 调整 `perceptual_similarity_threshold` (提高阈值)
2. 增加 `short_term_search_top_k`
3. 启用 `enable_judge_retrieval` 使用智能判断
4. 检查向量生成是否正常

## 📊 性能指标

### 预期性能

- **感知记忆添加**: <5ms
- **短期记忆检索**: <100ms
- **长期记忆转移**: 每条 1-3秒（LLM调用）
- **智能检索**: 200-500ms（含Judge决策）

### 资源占用

- **内存**: 
  - 感知层: ~10MB (50块 × 5消息)
  - 短期层: ~20MB (100条结构化记忆)
  - 长期层: 依赖现有记忆图系统
- **磁盘**: 
  - JSON文件: ~1-5MB
  - 向量存储: ~10-50MB (ChromaDB)

## 🔗 相关文档

- [数据库架构文档](./database_refactoring_completion.md)
- [记忆图谱指南](./memory_graph_guide.md)
- [统一调度器指南](./unified_scheduler_guide.md)
- [插件开发文档](./plugins/quick-start.md)

## 🤝 贡献与反馈

如果您在使用过程中遇到问题或有改进建议，请：

1. 查看 GitHub Issues
2. 提交详细的错误报告（包含日志）
3. 参考示例代码和最佳实践

---

**版本**: 1.0.0  
**最后更新**: 2025-01-13  
**维护者**: MoFox_Bot 开发团队

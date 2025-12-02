"""
记忆清理脚本

功能：
1. 遍历所有长期记忆
2. 使用 LLM 评估每条记忆的价值
3. 删除无效/低价值记忆
4. 合并/精简相似记忆

使用方式：
cd Bot
python scripts/memory_cleaner.py [--dry-run] [--batch-size 10]
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.config import model_config
from src.llm_models.utils_model import LLMRequest
from src.config.config import global_config


# ==================== 配置 ====================

# LLM 评估提示词
EVALUATION_PROMPT = """你是一个非常严格的记忆价值评估专家。你的任务是大幅清理低质量记忆，只保留真正有价值的信息。

## 核心原则：宁缺毋滥！
- 默认态度是 DELETE（删除）
- 只有非常明确、有具体信息的记忆才能保留
- 有任何疑虑就删除

## 必须删除的记忆（直接 delete）：

1. **无意义内容**：
   - 单字/短语回复："？"、"1"、"好"、"哦"、"啊"、"嗯"、"哈哈"、"呜呜"
   - 表情包、颜文字、emoji 刷屏
   - "某人发了图片/表情/语音"等无实质内容
   - 乱码、无法理解的内容

2. **模糊/缺乏上下文的信息**：
   - "用户说了什么" 但没有具体内容
   - "某人和某人聊天" 但不知道聊什么
   - 泛泛的描述如"用户很开心"但不知道原因
   - 指代不明的内容（"那个"、"这个"、"它"）

3. **水群/无营养聊天**：
   - 群内的日常寒暄、问好
   - 闲聊、灌水、抖机灵
   - 无实际信息的互动
   - 复读、玩梗、接龙
   - 讨论与用户个人无关的话题

4. **临时/过时信息**：
   - 游戏状态、在线状态
   - 已过期的活动、事件
   - 天气、时间等即时信息
   - "刚才"、"现在"等时效性表述

5. **重复/冗余**：
   - 相同内容的多条记录
   - 可以合并的相似信息

6. **AI自身的记忆**：
   - AI说了什么话
   - AI的回复内容
   - AI的想法/计划

## 可以保留的记忆（必须同时满足）：

1. **有明确的主体**：知道是谁（具体的用户名/昵称/ID）
2. **有具体的内容**：知道具体说了什么、做了什么、是什么
3. **有长期价值**：这个信息在一个月后仍然有参考意义

**保留示例**：
- "用户张三说他是程序员，在杭州工作" ✅
- "李四说他喜欢打篮球，每周三都会去" ✅  
- "小明说他女朋友叫小红，在一起2年了" ✅
- "用户A的生日是3月15日" ✅

**删除示例**：
- "用户发了个表情" ❌
- "群里在聊天" ❌
- "某人说了什么" ❌
- "今天天气很好" ❌
- "哈哈哈太好笑了" ❌

## 待评估记忆

{memories}

## 输出要求

严格按以下 JSON 格式输出，不要有任何其他内容：

```json
{{
    "evaluations": [
        {{
            "memory_id": "记忆的ID（从上面复制）",
            "action": "delete",
            "reason": "删除原因"
        }},
        {{
            "memory_id": "另一个ID",
            "action": "keep", 
            "reason": "保留原因"
        }}
    ]
}}
```

action 只能是：
- "delete": 删除（应该是大多数）
- "keep": 保留（只有高价值记忆）
- "summarize": 精简（很少用，只有内容过长但有价值时）

如果 action 是 summarize，需要加 "new_content": "精简后的内容"

直接输出 JSON，不要任何解释。"""


class MemoryCleaner:
    """记忆清理器"""

    def __init__(self, dry_run: bool = True, batch_size: int = 10, concurrency: int = 5):
        """
        初始化清理器
        
        Args:
            dry_run: 是否为模拟运行（不实际修改数据）
            batch_size: 每批处理的记忆数量
            concurrency: 并发请求数
        """
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.concurrency = concurrency
        self.data_dir = project_root / "data" / "memory_graph"
        self.memory_file = self.data_dir / "memory_graph.json"
        self.backup_dir = self.data_dir / "backups"
        
        # 并发控制
        self.semaphore: asyncio.Semaphore | None = None
        
        # 统计信息
        self.stats = {
            "total": 0,
            "kept": 0,
            "deleted": 0,
            "summarized": 0,
            "errors": 0,
            "deleted_nodes": 0,
            "deleted_edges": 0,
        }
        
        # 日志文件
        self.log_file = self.data_dir / f"cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self.cleanup_log = []

    def load_memories(self) -> dict:
        """加载记忆数据"""
        print(f"📂 加载记忆文件: {self.memory_file}")
        
        if not self.memory_file.exists():
            raise FileNotFoundError(f"记忆文件不存在: {self.memory_file}")
        
        with open(self.memory_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return data

    def extract_memory_text(self, memory_dict: dict) -> str:
        """从记忆字典中提取可读文本"""
        parts = []
        
        # 提取基本信息
        memory_id = memory_dict.get("id", "unknown")
        parts.append(f"ID: {memory_id}")
        
        # 提取节点内容
        nodes = memory_dict.get("nodes", [])
        for node in nodes:
            node_type = node.get("node_type", "")
            content = node.get("content", "")
            if content:
                parts.append(f"[{node_type}] {content}")
        
        # 提取边关系
        edges = memory_dict.get("edges", [])
        for edge in edges:
            relation = edge.get("relation", "")
            if relation:
                parts.append(f"关系: {relation}")
        
        # 提取元数据
        metadata = memory_dict.get("metadata", {})
        if metadata:
            if "context" in metadata:
                parts.append(f"上下文: {metadata['context']}")
            if "emotion" in metadata:
                parts.append(f"情感: {metadata['emotion']}")
        
        # 提取重要性和状态
        importance = memory_dict.get("importance", 0)
        status = memory_dict.get("status", "unknown")
        created_at = memory_dict.get("created_at", "unknown")
        
        parts.append(f"重要性: {importance}, 状态: {status}, 创建时间: {created_at}")
        
        return "\n".join(parts)

    async def evaluate_batch(self, memories: list[dict], batch_id: int = 0) -> tuple[int, list[dict]]:
        """
        使用 LLM 评估一批记忆（带并发控制）
        
        Args:
            memories: 记忆字典列表
            batch_id: 批次编号
            
        Returns:
            (批次ID, 评估结果列表)
        """
        async with self.semaphore:
            # 构建记忆文本
            memory_texts = []
            for i, mem in enumerate(memories):
                text = self.extract_memory_text(mem)
                memory_texts.append(f"=== 记忆 {i+1} ===\n{text}")
            
            combined_text = "\n\n".join(memory_texts)
            prompt = EVALUATION_PROMPT.format(memories=combined_text)
            
            try:
                # 使用 LLMRequest 调用模型
                if model_config is None:
                    raise RuntimeError("model_config 未初始化，请确保已加载配置")
                task_config = model_config.model_task_config.utils
                llm = LLMRequest(task_config, request_type="memory_cleanup")
                response_text, (reasoning, model_name, _) = await llm.generate_response_async(
                    prompt=prompt,
                    temperature=0.2,
                    max_tokens=4000,
                )
                
                print(f"   ✅ 批次 {batch_id} 完成 (模型: {model_name})")
                
                # 解析 JSON 响应
                response_text = response_text.strip()
                
                # 尝试提取 JSON
                if "```json" in response_text:
                    json_start = response_text.find("```json") + 7
                    json_end = response_text.find("```", json_start)
                    response_text = response_text[json_start:json_end].strip()
                elif "```" in response_text:
                    json_start = response_text.find("```") + 3
                    json_end = response_text.find("```", json_start)
                    response_text = response_text[json_start:json_end].strip()
                
                result = json.loads(response_text)
                evaluations = result.get("evaluations", [])
                
                # 为评估结果添加实际的 memory_id
                for j, eval_result in enumerate(evaluations):
                    if j < len(memories):
                        eval_result["memory_id"] = memories[j].get("id", f"unknown_{batch_id}_{j}")
                
                return (batch_id, evaluations)
                
            except json.JSONDecodeError as e:
                print(f"   ❌ 批次 {batch_id} JSON 解析失败: {e}")
                return (batch_id, [])
            except Exception as e:
                print(f"   ❌ 批次 {batch_id} LLM 调用失败: {e}")
                return (batch_id, [])

    async def initialize(self):
        """初始化（创建信号量）"""
        self.semaphore = asyncio.Semaphore(self.concurrency)
        print(f"🔧 初始化完成 (并发数: {self.concurrency})")

    def create_backup(self, data: dict):
        """创建数据备份"""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = self.backup_dir / f"memory_graph_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        print(f"💾 创建备份: {backup_file}")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return backup_file

    def apply_changes(self, data: dict, evaluations: list[dict]) -> dict:
        """
        应用评估结果到数据
        
        Args:
            data: 原始数据
            evaluations: 评估结果列表
            
        Returns:
            修改后的数据
        """
        # 创建评估结果索引
        eval_map = {e["memory_id"]: e for e in evaluations if "memory_id" in e}
        
        # 需要删除的记忆 ID
        to_delete = set()
        # 需要更新的记忆
        to_update = {}
        
        for eval_result in evaluations:
            memory_id = eval_result.get("memory_id")
            action = eval_result.get("action")
            
            if action == "delete":
                to_delete.add(memory_id)
                self.stats["deleted"] += 1
                self.cleanup_log.append({
                    "memory_id": memory_id,
                    "action": "delete",
                    "reason": eval_result.get("reason", ""),
                    "timestamp": datetime.now().isoformat()
                })
            elif action == "summarize":
                to_update[memory_id] = eval_result.get("new_content")
                self.stats["summarized"] += 1
                self.cleanup_log.append({
                    "memory_id": memory_id,
                    "action": "summarize",
                    "reason": eval_result.get("reason", ""),
                    "new_content": eval_result.get("new_content"),
                    "timestamp": datetime.now().isoformat()
                })
            else:
                self.stats["kept"] += 1
        
        if self.dry_run:
            print("🔍 [DRY RUN] 不实际修改数据")
            return data
        
        # 实际修改数据
        # 1. 删除记忆
        memories = data.get("memories", {})
        for mem_id in to_delete:
            if mem_id in memories:
                del memories[mem_id]
        
        # 2. 更新记忆内容
        for mem_id, new_content in to_update.items():
            if mem_id in memories:
                # 更新主题节点的内容
                memory = memories[mem_id]
                for node in memory.get("nodes", []):
                    if node.get("node_type") in ["主题", "topic", "TOPIC"]:
                        node["content"] = new_content
                        break
        
        # 3. 清理孤立节点和边
        data = self.cleanup_orphaned_nodes_and_edges(data)
        
        return data
    
    def cleanup_orphaned_nodes_and_edges(self, data: dict) -> dict:
        """
        清理孤立的节点和边
        
        孤立节点：其 metadata.memory_ids 中的所有记忆都已被删除
        孤立边：其 source 或 target 节点已被删除
        """
        print("\n🔗 清理孤立节点和边...")
        
        # 获取当前所有有效的记忆 ID
        valid_memory_ids = set(data.get("memories", {}).keys())
        print(f"   有效记忆数: {len(valid_memory_ids)}")
        
        # 清理节点
        nodes = data.get("nodes", [])
        original_node_count = len(nodes)
        
        valid_nodes = []
        valid_node_ids = set()
        
        for node in nodes:
            node_id = node.get("id")
            metadata = node.get("metadata", {})
            memory_ids = metadata.get("memory_ids", [])
            
            # 检查节点关联的记忆是否还存在
            if memory_ids:
                # 过滤掉已删除的记忆 ID
                remaining_memory_ids = [mid for mid in memory_ids if mid in valid_memory_ids]
                
                if remaining_memory_ids:
                    # 更新 metadata 中的 memory_ids
                    metadata["memory_ids"] = remaining_memory_ids
                    valid_nodes.append(node)
                    valid_node_ids.add(node_id)
                # 如果没有剩余的有效记忆 ID，节点被丢弃
            else:
                # 没有 memory_ids 的节点（可能是其他方式创建的），检查是否被某个记忆引用
                # 保守处理：保留这些节点
                valid_nodes.append(node)
                valid_node_ids.add(node_id)
        
        deleted_nodes = original_node_count - len(valid_nodes)
        data["nodes"] = valid_nodes
        print(f"   ✅ 节点: {original_node_count} → {len(valid_nodes)} (删除 {deleted_nodes})")
        
        # 清理边
        edges = data.get("edges", [])
        original_edge_count = len(edges)
        
        valid_edges = []
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            
            # 只保留两端节点都存在的边
            if source in valid_node_ids and target in valid_node_ids:
                valid_edges.append(edge)
        
        deleted_edges = original_edge_count - len(valid_edges)
        data["edges"] = valid_edges
        print(f"   ✅ 边: {original_edge_count} → {len(valid_edges)} (删除 {deleted_edges})")
        
        # 更新统计
        self.stats["deleted_nodes"] = deleted_nodes
        self.stats["deleted_edges"] = deleted_edges
        
        return data

    def save_data(self, data: dict):
        """保存修改后的数据"""
        if self.dry_run:
            print("🔍 [DRY RUN] 跳过保存")
            return
        
        print(f"💾 保存数据到: {self.memory_file}")
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_log(self):
        """保存清理日志"""
        print(f"📝 保存清理日志到: {self.log_file}")
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump({
                "stats": self.stats,
                "dry_run": self.dry_run,
                "timestamp": datetime.now().isoformat(),
                "log": self.cleanup_log
            }, f, ensure_ascii=False, indent=2)

    async def run(self):
        """运行清理流程"""
        print("=" * 60)
        print("🧹 记忆清理脚本 (高并发版)")
        print("=" * 60)
        print(f"模式: {'模拟运行 (DRY RUN)' if self.dry_run else '实际执行'}")
        print(f"批次大小: {self.batch_size}")
        print(f"并发数: {self.concurrency}")
        print("=" * 60)
        
        # 初始化
        await self.initialize()
        
        # 加载数据
        data = self.load_memories()
        
        # 获取所有记忆
        memories = data.get("memories", {})
        memory_list = list(memories.values())
        self.stats["total"] = len(memory_list)
        
        print(f"📊 总记忆数: {self.stats['total']}")
        
        if not memory_list:
            print("⚠️ 没有记忆需要处理")
            return
        
        # 创建备份
        if not self.dry_run:
            self.create_backup(data)
        
        # 分批
        batches = []
        for i in range(0, len(memory_list), self.batch_size):
            batch = memory_list[i:i + self.batch_size]
            batches.append(batch)
        
        total_batches = len(batches)
        print(f"📦 共 {total_batches} 个批次，开始并发处理...\n")
        
        # 并发处理所有批次
        start_time = datetime.now()
        tasks = [
            self.evaluate_batch(batch, batch_id=idx)
            for idx, batch in enumerate(batches)
        ]
        
        # 使用 asyncio.gather 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        # 收集所有评估结果
        all_evaluations = []
        success_count = 0
        error_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                print(f"   ❌ 批次异常: {result}")
                error_count += 1
            elif isinstance(result, tuple):
                batch_id, evaluations = result
                if evaluations:
                    all_evaluations.extend(evaluations)
                    success_count += 1
                else:
                    error_count += 1
        
        print(f"\n⏱️ 并发处理完成，耗时 {elapsed:.1f} 秒")
        print(f"   成功批次: {success_count}/{total_batches}, 失败: {error_count}")
        
        # 统计评估结果
        delete_count = sum(1 for e in all_evaluations if e.get("action") == "delete")
        keep_count = sum(1 for e in all_evaluations if e.get("action") == "keep")
        summarize_count = sum(1 for e in all_evaluations if e.get("action") == "summarize")
        
        print(f"   📊 评估结果: 保留 {keep_count}, 删除 {delete_count}, 精简 {summarize_count}")
        
        # 应用更改
        print("\n" + "=" * 60)
        print("📊 应用更改...")
        data = self.apply_changes(data, all_evaluations)
        
        # 保存数据
        self.save_data(data)
        
        # 保存日志
        self.save_log()
        
        # 打印统计
        print("\n" + "=" * 60)
        print("📊 清理统计")
        print("=" * 60)
        print(f"总记忆数: {self.stats['total']}")
        print(f"保留: {self.stats['kept']}")
        print(f"删除: {self.stats['deleted']}")
        print(f"精简: {self.stats['summarized']}")
        print(f"删除节点: {self.stats['deleted_nodes']}")
        print(f"删除边: {self.stats['deleted_edges']}")
        print(f"错误: {self.stats['errors']}")
        print(f"处理速度: {self.stats['total'] / elapsed:.1f} 条/秒")
        print("=" * 60)
        
        if self.dry_run:
            print("\n⚠️ 这是模拟运行，实际数据未被修改")
            print("如要实际执行，请移除 --dry-run 参数")

    async def run_cleanup_only(self):
        """只清理孤立节点和边，不重新评估记忆"""
        print("=" * 60)
        print("🔗 孤立节点/边清理模式")
        print("=" * 60)
        print(f"模式: {'模拟运行 (DRY RUN)' if self.dry_run else '实际执行'}")
        print("=" * 60)
        
        # 加载数据
        data = self.load_memories()
        
        # 统计原始数据
        memories = data.get("memories", {})
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        
        print(f"📊 当前状态: {len(memories)} 条记忆, {len(nodes)} 个节点, {len(edges)} 条边")
        
        if not self.dry_run:
            self.create_backup(data)
        
        # 清理孤立节点和边
        if self.dry_run:
            # 模拟运行：统计但不修改
            valid_memory_ids = set(memories.keys())
            
            # 统计要删除的节点
            nodes_to_keep = 0
            for node in nodes:
                metadata = node.get("metadata", {})
                memory_ids = metadata.get("memory_ids", [])
                if memory_ids:
                    remaining = [mid for mid in memory_ids if mid in valid_memory_ids]
                    if remaining:
                        nodes_to_keep += 1
                else:
                    nodes_to_keep += 1
            
            nodes_to_delete = len(nodes) - nodes_to_keep
            
            # 统计要删除的边（需要先确定哪些节点会被保留）
            valid_node_ids = set()
            for node in nodes:
                metadata = node.get("metadata", {})
                memory_ids = metadata.get("memory_ids", [])
                if memory_ids:
                    remaining = [mid for mid in memory_ids if mid in valid_memory_ids]
                    if remaining:
                        valid_node_ids.add(node.get("id"))
                else:
                    valid_node_ids.add(node.get("id"))
            
            edges_to_keep = sum(1 for e in edges if e.get("source") in valid_node_ids and e.get("target") in valid_node_ids)
            edges_to_delete = len(edges) - edges_to_keep
            
            print(f"\n🔍 [DRY RUN] 预计清理:")
            print(f"   节点: {len(nodes)} → {nodes_to_keep} (删除 {nodes_to_delete})")
            print(f"   边: {len(edges)} → {edges_to_keep} (删除 {edges_to_delete})")
            print("\n⚠️ 这是模拟运行，实际数据未被修改")
            print("如要实际执行，请移除 --dry-run 参数")
        else:
            data = self.cleanup_orphaned_nodes_and_edges(data)
            self.save_data(data)
            
            print(f"\n✅ 清理完成!")
            print(f"   删除节点: {self.stats['deleted_nodes']}")
            print(f"   删除边: {self.stats['deleted_edges']}")


async def main():
    parser = argparse.ArgumentParser(description="记忆清理脚本 (高并发版)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟运行，不实际修改数据"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="每批处理的记忆数量 (默认: 10)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="并发请求数 (默认: 10)"
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="只清理孤立节点和边，不重新评估记忆"
    )
    
    args = parser.parse_args()
    
    cleaner = MemoryCleaner(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        concurrency=args.concurrency,
    )
    
    if args.cleanup_only:
        await cleaner.run_cleanup_only()
    else:
        await cleaner.run()


if __name__ == "__main__":
    asyncio.run(main())

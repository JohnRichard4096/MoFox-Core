"""
记忆格式化工具

提供将记忆对象格式化为提示词的功能，使用 "主体-主题(属性)" 格式。
"""

from src.memory_graph.models import Memory, MemoryNode, NodeType
from src.memory_graph.models import ShortTermMemory


def get_memory_type_label(memory_type: str) -> str:
    """
    获取记忆类型的中文标签

    Args:
        memory_type: 记忆类型（英文）

    Returns:
        中文标签
    """
    type_mapping = {
        "事实": "事实",
        "事件": "事件",
        "观点": "观点",
        "关系": "关系",
        "目标": "目标",
        "计划": "计划",
        "fact": "事实",
        "event": "事件",
        "opinion": "观点",
        "relation": "关系",
        "goal": "目标",
        "plan": "计划",
        "unknown": "未知",
    }
    return type_mapping.get(memory_type.lower(), memory_type)


def format_memory_for_prompt(memory: Memory | ShortTermMemory, include_metadata: bool = True) -> str:
    """
    格式化记忆为提示词文本

    使用 "主体-主题(属性)" 格式，例如：
    - "张三-职业(程序员, 公司=MoFox)"
    - "小明-喜欢(Python, 原因=简洁优雅)"
    - "拾风-地址(https://mofox.com)"

    Args:
        memory: Memory 或 ShortTermMemory 对象
        include_metadata: 是否包含元数据（如重要性、时间等）

    Returns:
        格式化后的记忆文本
    """
    if isinstance(memory, ShortTermMemory):
        return _format_short_term_memory(memory, include_metadata)
    elif isinstance(memory, Memory):
        return _format_long_term_memory(memory, include_metadata)
    else:
        return str(memory)


def _format_short_term_memory(mem: ShortTermMemory, include_metadata: bool) -> str:
    """
    格式化短期记忆

    Args:
        mem: ShortTermMemory 对象
        include_metadata: 是否包含元数据

    Returns:
        格式化后的文本
    """
    parts = []

    # 主体
    subject = mem.subject or ""
    # 主题
    topic = mem.topic or ""
    # 客体
    obj = mem.object or ""

    # 构建基础格式：主体-主题
    if subject and topic:
        base = f"{subject}-{topic}"
    elif subject:
        base = subject
    elif topic:
        base = topic
    else:
        # 如果没有结构化字段，使用 content
        # 防御性编程：确保 content 是字符串
        if isinstance(mem.content, list):
            return " ".join(str(item) for item in mem.content)
        return str(mem.content) if mem.content else ""

    # 添加客体和属性
    attr_parts = []
    if obj:
        attr_parts.append(obj)

    # 添加属性
    if mem.attributes:
        for key, value in mem.attributes.items():
            if value:
                attr_parts.append(f"{key}={value}")

    # 组合
    if attr_parts:
        result = f"{base}({', '.join(attr_parts)})"
    else:
        result = base

    # 添加元数据（可选）
    if include_metadata:
        metadata_parts = []
        if mem.memory_type:
            metadata_parts.append(f"类型:{get_memory_type_label(mem.memory_type)}")
        if mem.importance > 0:
            metadata_parts.append(f"重要性:{mem.importance:.2f}")

        if metadata_parts:
            result = f"{result} [{', '.join(metadata_parts)}]"

    return result


def _format_long_term_memory(mem: Memory, include_metadata: bool) -> str:
    """
    格式化长期记忆（Memory 对象）

    Args:
        mem: Memory 对象
        include_metadata: 是否包含元数据

    Returns:
        格式化后的文本
    """
    from src.memory_graph.models import EdgeType

    # 获取主体节点
    subject_node = mem.get_subject_node()
    if not subject_node:
        return mem.to_text()

    subject = subject_node.content

    # 查找主题节点
    topic_node = None
    for edge in mem.edges:
        edge_type = edge.edge_type.value if hasattr(edge.edge_type, 'value') else str(edge.edge_type)
        if edge_type == "记忆类型" and edge.source_id == mem.subject_id:
            topic_node = mem.get_node_by_id(edge.target_id)
            break

    if not topic_node:
        return subject

    topic = topic_node.content

    # 基础格式：主体-主题
    base = f"{subject}-{topic}"

    # 收集客体和属性
    attr_parts = []

    # 查找客体节点（通过核心关系边）
    for edge in mem.edges:
        edge_type = edge.edge_type.value if hasattr(edge.edge_type, 'value') else str(edge.edge_type)
        if edge_type == "核心关系" and edge.source_id == topic_node.id:
            obj_node = mem.get_node_by_id(edge.target_id)
            if obj_node:
                # 如果有关系名称，使用关系名称
                if edge.relation and edge.relation != "未知":
                    attr_parts.append(f"{edge.relation}={obj_node.content}")
                else:
                    attr_parts.append(obj_node.content)

    # 查找属性节点
    for node in mem.nodes:
        if node.node_type == NodeType.ATTRIBUTE:
            # 属性节点的 content 格式可能是 "key=value" 或 "value"
            attr_parts.append(node.content)

    # 组合
    if attr_parts:
        result = f"{base}({', '.join(attr_parts)})"
    else:
        result = base

    # 添加元数据（可选）
    if include_metadata:
        metadata_parts = []
        if mem.memory_type:
            type_value = mem.memory_type.value if hasattr(mem.memory_type, 'value') else str(mem.memory_type)
            metadata_parts.append(f"类型:{get_memory_type_label(type_value)}")
        if mem.importance > 0:
            metadata_parts.append(f"重要性:{mem.importance:.2f}")

        if metadata_parts:
            result = f"{result} [{', '.join(metadata_parts)}]"

    return result


def format_memories_block(
    memories: list[Memory | ShortTermMemory],
    title: str = "相关记忆",
    max_count: int = 10,
    include_metadata: bool = False,
) -> str:
    """
    格式化多个记忆为提示词块

    Args:
        memories: 记忆列表
        title: 块标题
        max_count: 最多显示的记忆数量
        include_metadata: 是否包含元数据

    Returns:
        格式化后的记忆块
    """
    if not memories:
        return ""

    lines = [f"### 🧠 {title}", ""]

    for mem in memories[:max_count]:
        formatted = format_memory_for_prompt(mem, include_metadata=include_metadata)
        if formatted:
            lines.append(f"- {formatted}")

    return "\n".join(lines)

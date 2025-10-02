"""
记忆系统相关的映射表和工具函数
提供记忆类型、置信度、重要性等的中文标签映射
"""

# 记忆类型到中文标签的完整映射表
MEMORY_TYPE_CHINESE_MAPPING = {
    "personal_fact": "个人事实",
    "preference": "偏好",
    "event": "事件",
    "opinion": "观点",
    "relationship": "人际关系",
    "emotion": "情感状态",
    "knowledge": "知识信息",
    "skill": "技能能力",
    "goal": "目标计划",
    "experience": "经验教训",
    "contextual": "上下文信息",
    "unknown": "未知",
}

# 置信度等级到中文标签的映射表
CONFIDENCE_LEVEL_CHINESE_MAPPING = {
    1: "低置信度",
    2: "中等置信度",
    3: "高置信度",
    4: "已验证",
    "LOW": "低置信度",
    "MEDIUM": "中等置信度",
    "HIGH": "高置信度",
    "VERIFIED": "已验证",
    "unknown": "未知",
}

# 重要性等级到中文标签的映射表
IMPORTANCE_LEVEL_CHINESE_MAPPING = {
    1: "低重要性",
    2: "一般重要性",
    3: "高重要性",
    4: "关键重要性",
    "LOW": "低重要性",
    "NORMAL": "一般重要性",
    "HIGH": "高重要性",
    "CRITICAL": "关键重要性",
    "unknown": "未知",
}


def get_memory_type_chinese_label(memory_type: str) -> str:
    """获取记忆类型的中文标签

    Args:
        memory_type: 记忆类型字符串

    Returns:
        str: 对应的中文标签，如果找不到则返回"未知"
    """
    return MEMORY_TYPE_CHINESE_MAPPING.get(memory_type, "未知")


def get_confidence_level_chinese_label(level) -> str:
    """获取置信度等级的中文标签

    Args:
        level: 置信度等级（可以是数字、字符串或枚举实例）

    Returns:
        str: 对应的中文标签，如果找不到则返回"未知"
    """
    # 处理枚举实例
    if hasattr(level, "value"):
        level = level.value

    # 处理数字
    if isinstance(level, int):
        return CONFIDENCE_LEVEL_CHINESE_MAPPING.get(level, "未知")

    # 处理字符串
    if isinstance(level, str):
        level_upper = level.upper()
        return CONFIDENCE_LEVEL_CHINESE_MAPPING.get(level_upper, "未知")

    return "未知"


def get_importance_level_chinese_label(level) -> str:
    """获取重要性等级的中文标签

    Args:
        level: 重要性等级（可以是数字、字符串或枚举实例）

    Returns:
        str: 对应的中文标签，如果找不到则返回"未知"
    """
    # 处理枚举实例
    if hasattr(level, "value"):
        level = level.value

    # 处理数字
    if isinstance(level, int):
        return IMPORTANCE_LEVEL_CHINESE_MAPPING.get(level, "未知")

    # 处理字符串
    if isinstance(level, str):
        level_upper = level.upper()
        return IMPORTANCE_LEVEL_CHINESE_MAPPING.get(level_upper, "未知")

    return "未知"

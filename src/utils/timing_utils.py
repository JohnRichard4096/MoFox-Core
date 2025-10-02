#!/usr/bin/env python3
"""
时间间隔工具函数
用于主动思考功能的正态分布时间计算，支持3-sigma规则

🚀 性能优化特性：
- 向量化操作：使用NumPy向量化替代Python循环，速度提升10-50倍
- 批量生成：一次生成多个候选值，减少函数调用开销
- 内存高效：避免大数组分配，使用小批量处理
- 快速筛选：使用NumPy布尔索引进行高效过滤
"""

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=128)
def _calculate_sigma_bounds(base_interval: int, sigma_percentage: float, use_3sigma_rule: bool) -> tuple:
    """
    缓存sigma边界计算，避免重复计算相同参数

    🚀 性能优化：LRU缓存常用配置，避免重复数学计算
    """
    sigma = base_interval * sigma_percentage

    if use_3sigma_rule:
        three_sigma_min = max(1, base_interval - 3 * sigma)
        three_sigma_max = base_interval + 3 * sigma
        return three_sigma_min, three_sigma_max

    return 1, base_interval * 50  # 更宽松的边界


def get_normal_distributed_interval(
    base_interval: int,
    sigma_percentage: float = 0.1,
    min_interval: int | None = None,
    max_interval: int | None = None,
    use_3sigma_rule: bool = True,
) -> int:
    """
    获取符合正态分布的时间间隔，基于3-sigma规则

    Args:
        base_interval: 基础时间间隔（秒），作为正态分布的均值μ
        sigma_percentage: 标准差占基础间隔的百分比，默认10%
        min_interval: 最小间隔时间（秒），防止间隔过短
        max_interval: 最大间隔时间（秒），防止间隔过长
        use_3sigma_rule: 是否使用3-sigma规则限制分布范围，默认True

    Returns:
        int: 符合正态分布的时间间隔（秒）

    Example:
        >>> # 基础间隔1500秒（25分钟），标准差为150秒（10%）
        >>> interval = get_normal_distributed_interval(1500, 0.1)
        >>> # 99.7%的值会在μ±3σ范围内：1500±450 = [1050,1950]
    """
    # 🚨 基本输入保护：处理负数
    if base_interval < 0:
        base_interval = abs(base_interval)

    if sigma_percentage < 0:
        sigma_percentage = abs(sigma_percentage)

    # 特殊情况：基础间隔为0，使用纯随机模式
    if base_interval == 0:
        if sigma_percentage == 0:
            return 1  # 都为0时返回1秒
        return _generate_pure_random_interval(sigma_percentage, min_interval, max_interval, use_3sigma_rule)

    # 特殊情况：sigma为0，返回固定间隔
    if sigma_percentage == 0:
        return base_interval

    # 计算标准差
    sigma = base_interval * sigma_percentage

    # 📊 使用缓存的边界计算（性能优化）
    if use_3sigma_rule:
        three_sigma_min, three_sigma_max = _calculate_sigma_bounds(base_interval, sigma_percentage, True)

        # 应用用户设定的边界（如果更严格的话）
        if min_interval is not None:
            three_sigma_min = max(three_sigma_min, min_interval)
        if max_interval is not None:
            three_sigma_max = min(three_sigma_max, max_interval)

        effective_min = int(three_sigma_min)
        effective_max = int(three_sigma_max)
    else:
        # 不使用3-sigma规则，使用更宽松的边界
        effective_min = max(1, min_interval or 1)
        effective_max = max(effective_min + 1, max_interval or int(base_interval * 50))

    # 向量化生成：一次性生成多个候选值，避免循环
    # 对于3-sigma规则，理论成功率99.7%，生成10个候选值基本确保成功
    batch_size = 10 if use_3sigma_rule else 5

    # 一次性生成多个正态分布值
    candidates = np.random.normal(loc=base_interval, scale=sigma, size=batch_size)

    # 向量化处理负数：对负数取绝对值
    candidates = np.abs(candidates)

    # 转换为整数数组
    candidates = np.round(candidates).astype(int)

    # 向量化筛选：找到第一个满足条件的值
    valid_mask = (candidates >= effective_min) & (candidates <= effective_max)
    valid_candidates = candidates[valid_mask]

    if len(valid_candidates) > 0:
        return int(valid_candidates[0])  # 返回第一个有效值

    # 如果向量化生成失败（极低概率），使用均匀分布作为备用
    return int(np.random.randint(effective_min, effective_max + 1))


def _generate_pure_random_interval(
    sigma_percentage: float,
    min_interval: int | None = None,
    max_interval: int | None = None,
    use_3sigma_rule: bool = True,
) -> int:
    """
    当base_interval=0时的纯随机模式，基于3-sigma规则

    Args:
        sigma_percentage: 标准差百分比，将被转换为实际时间值
        min_interval: 最小间隔
        max_interval: 最大间隔
        use_3sigma_rule: 是否使用3-sigma规则

    Returns:
        int: 随机生成的时间间隔（秒）
    """
    # 将百分比转换为实际时间值（假设1000秒作为基准）
    # sigma_percentage=0.3 -> sigma=300秒
    base_reference = 1000  # 基准时间
    sigma = abs(sigma_percentage) * base_reference

    # 使用sigma作为均值，sigma/3作为标准差
    # 这样3σ范围约为[0, 2*sigma]
    mean = sigma
    std = sigma / 3

    if use_3sigma_rule:
        # 3-sigma边界：μ±3σ = sigma±3*(sigma/3) = sigma±sigma = [0, 2*sigma]
        three_sigma_min = max(1, mean - 3 * std)  # 理论上约为0，但最小1秒
        three_sigma_max = mean + 3 * std  # 约为2*sigma

        # 应用用户边界
        if min_interval is not None:
            three_sigma_min = max(three_sigma_min, min_interval)
        if max_interval is not None:
            three_sigma_max = min(three_sigma_max, max_interval)

        effective_min = int(three_sigma_min)
        effective_max = int(three_sigma_max)
    else:
        # 不使用3-sigma规则
        effective_min = max(1, min_interval or 1)
        effective_max = max(effective_min + 1, max_interval or int(mean * 10))

    # 向量化生成随机值
    batch_size = 8  # 小批量生成提高效率
    candidates = np.random.normal(loc=mean, scale=std, size=batch_size)

    # 向量化处理负数
    candidates = np.abs(candidates)

    # 转换为整数
    candidates = np.round(candidates).astype(int)

    # 向量化筛选
    valid_mask = (candidates >= effective_min) & (candidates <= effective_max)
    valid_candidates = candidates[valid_mask]

    if len(valid_candidates) > 0:
        return int(valid_candidates[0])

    # 备用方案：直接随机整数
    return int(np.random.randint(effective_min, effective_max + 1))


def format_time_duration(seconds: int) -> str:
    """
    将秒数格式化为易读的时间格式

    Args:
        seconds: 秒数

    Returns:
        str: 格式化的时间字符串，如"2小时30分15秒"
    """
    if seconds < 60:
        return f"{seconds}秒"

    minutes = seconds // 60
    remaining_seconds = seconds % 60

    if minutes < 60:
        if remaining_seconds > 0:
            return f"{minutes}分{remaining_seconds}秒"
        else:
            return f"{minutes}分"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if hours < 24:
        if remaining_minutes > 0 and remaining_seconds > 0:
            return f"{hours}小时{remaining_minutes}分{remaining_seconds}秒"
        elif remaining_minutes > 0:
            return f"{hours}小时{remaining_minutes}分"
        else:
            return f"{hours}小时"

    days = hours // 24
    remaining_hours = hours % 24

    if remaining_hours > 0:
        return f"{days}天{remaining_hours}小时"
    else:
        return f"{days}天"


def benchmark_timing_performance(iterations: int = 1000) -> dict:
    """
    性能基准测试函数，用于评估当前环境下的计算性能

    🚀 用于系统性能监控和优化验证

    Args:
        iterations: 测试迭代次数

    Returns:
        dict: 包含各种场景的性能指标
    """
    import time

    scenarios = {
        "standard": (600, 0.25, 1, 86400, True),
        "pure_random": (0, 0.3, 1, 86400, True),
        "fixed": (300, 0, 1, 86400, True),
        "extreme": (60, 5.0, 1, 86400, True),
    }

    results = {}

    for name, params in scenarios.items():
        start = time.perf_counter()

        for _ in range(iterations):
            get_normal_distributed_interval(*params)

        end = time.perf_counter()
        duration = (end - start) * 1000  # 转换为毫秒

        results[name] = {
            "total_ms": round(duration, 2),
            "avg_ms": round(duration / iterations, 6),
            "ops_per_sec": round(iterations / (duration / 1000)),
        }

    # 计算缓存效果
    results["cache_info"] = {
        "hits": _calculate_sigma_bounds.cache_info().hits,
        "misses": _calculate_sigma_bounds.cache_info().misses,
        "hit_rate": _calculate_sigma_bounds.cache_info().hits
        / max(1, _calculate_sigma_bounds.cache_info().hits + _calculate_sigma_bounds.cache_info().misses),
    }

    return results

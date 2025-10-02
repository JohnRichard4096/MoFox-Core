from __future__ import annotations

from src.config.config import global_config, model_config


def resolve_embedding_dimension(fallback: int | None = None, *, sync_global: bool = True) -> int | None:
    """获取当前配置的嵌入向量维度。

    优先顺序：
    1. 模型配置中 `model_task_config.embedding.embedding_dimension`
    2. 机器人配置中 `lpmm_knowledge.embedding_dimension`
    3. 调用方提供的 fallback
    """

    candidates: list[int | None] = []

    try:
        embedding_task = getattr(model_config.model_task_config, "embedding", None)
        if embedding_task is not None:
            candidates.append(getattr(embedding_task, "embedding_dimension", None))
    except Exception:
        candidates.append(None)

    try:
        candidates.append(getattr(global_config.lpmm_knowledge, "embedding_dimension", None))
    except Exception:
        candidates.append(None)

    candidates.append(fallback)

    resolved: int | None = next((int(dim) for dim in candidates if dim and int(dim) > 0), None)

    if resolved and sync_global:
        try:
            if getattr(global_config.lpmm_knowledge, "embedding_dimension", None) != resolved:
                global_config.lpmm_knowledge.embedding_dimension = resolved  # type: ignore[attr-defined]
        except Exception:
            pass

    return resolved

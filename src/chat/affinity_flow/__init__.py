"""
亲和力流模块初始化文件
提供全局的AFC管理器实例
"""

# Avoid importing submodules at package import time to prevent circular imports.
# Consumers should import specific submodules directly, for example:
#   from src.chat.affinity_flow.afc_manager import afc_manager

__all__ = ["afc_manager", "AFCManager", "AffinityFlowChatter"]

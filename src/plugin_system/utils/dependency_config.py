from src.common.logger import get_logger

logger = get_logger("dependency_config")


class DependencyConfig:
    """依赖管理配置类 - 现在使用全局配置"""

    def __init__(self, global_config=None):
        self._global_config = global_config

    def _get_config(self):
        """获取全局配置对象"""
        if self._global_config is not None:
            return self._global_config

        # 延迟导入以避免循环依赖
        try:
            from src.config.config import global_config

            return global_config
        except ImportError:
            logger.warning("无法导入全局配置，使用默认设置")
            return None

    @property
    def auto_install(self) -> bool:
        """是否启用自动安装"""
        config = self._get_config()
        if config and hasattr(config, "dependency_management"):
            return config.dependency_management.auto_install
        return True

    @property
    def use_mirror(self) -> bool:
        """是否使用PyPI镜像源"""
        config = self._get_config()
        if config and hasattr(config, "dependency_management"):
            return config.dependency_management.use_mirror
        return False

    @property
    def mirror_url(self) -> str:
        """PyPI镜像源URL"""
        config = self._get_config()
        if config and hasattr(config, "dependency_management"):
            return config.dependency_management.mirror_url
        return ""

    @property
    def install_timeout(self) -> int:
        """安装超时时间（秒）"""
        config = self._get_config()
        if config and hasattr(config, "dependency_management"):
            return config.dependency_management.auto_install_timeout
        return 300

    @property
    def prompt_before_install(self) -> bool:
        """安装前是否提示用户"""
        config = self._get_config()
        if config and hasattr(config, "dependency_management"):
            return config.dependency_management.prompt_before_install
        return False


# 全局配置实例
_global_dependency_config: DependencyConfig | None = None


def get_dependency_config() -> DependencyConfig:
    """获取全局依赖配置实例"""
    global _global_dependency_config
    if _global_dependency_config is None:
        _global_dependency_config = DependencyConfig()
    return _global_dependency_config


def configure_dependency_settings(**kwargs) -> None:
    """配置依赖管理设置 - 注意：这个函数现在仅用于兼容性，实际配置需要修改bot_config.toml"""
    logger.info("依赖管理设置现在通过 bot_config.toml 的 [dependency_management] 节进行配置")
    logger.info(f"请求的配置更改: {kwargs}")
    logger.warning("configure_dependency_settings 函数仅用于兼容性，配置更改不会持久化")

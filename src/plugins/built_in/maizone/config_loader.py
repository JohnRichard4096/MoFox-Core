"""
MaiZone插件配置加载器

简化的配置文件加载系统，专注于基本的配置文件读取和写入功能。
支持TOML格式的配置文件，具有基本的类型转换和默认值处理。
"""

import toml
from typing import Dict, Any, Optional
from pathlib import Path

from src.common.logger import get_logger

logger = get_logger("MaiZone.ConfigLoader")


class MaiZoneConfigLoader:
    """MaiZone插件配置加载器 - 简化版"""
    
    def __init__(self, plugin_dir: str, config_filename: str = "config.toml"):
        """
        初始化配置加载器
        
        Args:
            plugin_dir: 插件目录路径
            config_filename: 配置文件名
        """
        self.plugin_dir = Path(plugin_dir)
        self.config_filename = config_filename
        self.config_file_path = self.plugin_dir / config_filename
        self.config_data: Dict[str, Any] = {}
        
        # 确保插件目录存在
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
    
    def load_config(self) -> bool:
        """
        加载配置文件
        
        Returns:
            bool: 是否成功加载
        """
        try:
            # 如果配置文件不存在，创建默认配置
            if not self.config_file_path.exists():
                logger.info(f"配置文件不存在，创建默认配置: {self.config_file_path}")
                self._create_default_config()
            
            # 加载配置文件
            with open(self.config_file_path, 'r', encoding='utf-8') as f:
                self.config_data = toml.load(f)
            
            logger.info(f"成功加载配置文件: {self.config_file_path}")
            return True
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            # 如果加载失败，使用默认配置
            self.config_data = self._get_default_config()
            return False
    
    def _create_default_config(self):
        """创建默认配置文件"""
        default_config = self._get_default_config()
        self._save_config_to_file(default_config)
        self.config_data = default_config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "plugin": {
                "enabled": True,
                "name": "MaiZone",
                "version": "2.1.0"
            },
            "qzone": {
                "qq": "",
                "auto_login": True,
                "check_interval": 300,
                "max_retries": 3
            },
            "ai": {
                "enabled": False,
                "model": "gpt-3.5-turbo",
                "max_tokens": 150,
                "temperature": 0.7
            },
            "monitor": {
                "enabled": False,
                "keywords": [],
                "check_friends": True,
                "check_groups": False
            },
            "scheduler": {
                "enabled": False,
                "schedules": []
            }
        }
    
    def _save_config_to_file(self, config_data: Dict[str, Any]):
        """保存配置到文件"""
        try:
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                toml.dump(config_data, f)
            logger.debug(f"配置已保存到: {self.config_file_path}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持嵌套键访问
        
        Args:
            key: 配置键名，支持嵌套访问如 "section.field"
            default: 默认值
            
        Returns:
            Any: 配置值或默认值
        """
        if not self.config_data:
            logger.warning("配置数据为空，返回默认值")
            return default
            
        keys = key.split('.')
        current = self.config_data
        
        try:
            for k in keys:
                if isinstance(current, dict) and k in current:
                    current = current[k]
                else:
                    return default
            return current
        except Exception as e:
            logger.warning(f"获取配置失败 {key}: {e}")
            return default
    
    def set_config(self, key: str, value: Any) -> bool:
        """
        设置配置值
        
        Args:
            key: 配置键名，格式为 "section.field"
            value: 配置值
            
        Returns:
            bool: 是否设置成功
        """
        try:
            keys = key.split('.')
            if len(keys) < 2:
                logger.error(f"配置键格式错误: {key}，应为 'section.field' 格式")
                return False
            
            # 获取或创建嵌套字典结构
            current = self.config_data
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                elif not isinstance(current[k], dict):
                    logger.error(f"配置路径冲突: {k} 不是字典类型")
                    return False
                current = current[k]
            
            # 设置最终值
            current[keys[-1]] = value
            logger.debug(f"设置配置: {key} = {value}")
            return True
            
        except Exception as e:
            logger.error(f"设置配置失败 {key}: {e}")
            return False
    
    def save_config(self) -> bool:
        """
        保存当前配置到文件
        
        Returns:
            bool: 是否保存成功
        """
        try:
            self._save_config_to_file(self.config_data)
            logger.info(f"配置已保存到: {self.config_file_path}")
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False
    
    def reload_config(self) -> bool:
        """
        重新加载配置文件
        
        Returns:
            bool: 是否重新加载成功
        """
        return self.load_config()
    
    def get_section(self, section_name: str) -> Optional[Dict[str, Any]]:
        """
        获取整个配置节
        
        Args:
            section_name: 配置节名称
            
        Returns:
            Optional[Dict[str, Any]]: 配置节数据或None
        """
        return self.config_data.get(section_name)
    
    def set_section(self, section_name: str, section_data: Dict[str, Any]) -> bool:
        """
        设置整个配置节
        
        Args:
            section_name: 配置节名称
            section_data: 配置节数据
            
        Returns:
            bool: 是否设置成功
        """
        try:
            if not isinstance(section_data, dict):
                logger.error(f"配置节数据必须为字典类型: {section_name}")
                return False
            
            self.config_data[section_name] = section_data
            logger.debug(f"设置配置节: {section_name}")
            return True
        except Exception as e:
            logger.error(f"设置配置节失败 {section_name}: {e}")
            return False
    
    def has_config(self, key: str) -> bool:
        """
        检查配置项是否存在
        
        Args:
            key: 配置键名
            
        Returns:
            bool: 配置项是否存在
        """
        keys = key.split('.')
        current = self.config_data
        
        try:
            for k in keys:
                if isinstance(current, dict) and k in current:
                    current = current[k]
                else:
                    return False
            return True
        except Exception:
            return False
    
    def get_config_info(self) -> Dict[str, Any]:
        """
        获取配置信息
        
        Returns:
            Dict[str, Any]: 配置信息
        """
        return {
            "config_file": str(self.config_file_path),
            "config_exists": self.config_file_path.exists(),
            "sections": list(self.config_data.keys()) if self.config_data else [],
            "loaded": bool(self.config_data)
        }
    
    def reset_to_default(self) -> bool:
        """
        重置为默认配置
        
        Returns:
            bool: 是否重置成功
        """
        try:
            self.config_data = self._get_default_config()
            return self.save_config()
        except Exception as e:
            logger.error(f"重置配置失败: {e}")
            return False

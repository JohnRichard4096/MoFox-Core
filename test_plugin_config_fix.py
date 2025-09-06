#!/usr/bin/env python3
"""
测试脚本用于验证LauchNapcatAdapterHandler的plugin_config修复
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.plugins.built_in.napcat_adapter_plugin.plugin import LauchNapcatAdapterHandler

def test_plugin_config_fix():
    """测试plugin_config修复"""
    print("测试LauchNapcatAdapterHandler的plugin_config修复...")
    
    # 创建测试配置
    test_config = {
        "napcat_server": {
            "mode": "reverse",
            "host": "localhost",
            "port": 8095
        },
        "maibot_server": {
            "host": "localhost",
            "port": 8000
        }
    }
    
    # 创建处理器实例
    handler = LauchNapcatAdapterHandler()
    
    # 设置插件配置（模拟事件管理器注册时的行为）
    handler.plugin_config = test_config
    
    print(f"设置的plugin_config: {handler.plugin_config}")
    
    # 测试配置访问
    if handler.plugin_config is not None and handler.plugin_config == test_config:
        print("✅ plugin_config修复成功！")
        print(f"✅ 可以正常访问配置: napcat_server.mode = {handler.plugin_config.get('napcat_server', {}).get('mode')}")
        return True
    else:
        print("❌ plugin_config修复失败！")
        print(f"❌ 当前plugin_config: {handler.plugin_config}")
        return False

if __name__ == "__main__":
    success = test_plugin_config_fix()
    sys.exit(0 if success else 1)
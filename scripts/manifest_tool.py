"""
插件Manifest管理命令行工具

提供插件manifest文件的创建、验证和管理功能
"""

import argparse
import os
import sys
from pathlib import Path

import orjson

from src.common.logger import get_logger
from src.plugin_system.utils.manifest_utils import (
    ManifestValidator,
)

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


logger = get_logger("manifest_tool")


def create_minimal_manifest(plugin_dir: str, plugin_name: str, description: str = "", author: str = "") -> bool:
    """创建最小化的manifest文件

    Args:
        plugin_dir: 插件目录
        plugin_name: 插件名称
        description: 插件描述
        author: 插件作者

    Returns:
        bool: 是否创建成功
    """
    manifest_path = os.path.join(plugin_dir, "_manifest.json")

    if os.path.exists(manifest_path):
        print(f"❌ Manifest文件已存在: {manifest_path}")
        return False

    # 创建最小化manifest
    minimal_manifest = {
        "manifest_version": 1,
        "name": plugin_name,
        "version": "1.0.0",
        "description": description or f"{plugin_name}插件",
        "author": {"name": author or "Unknown"},
    }

    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(orjson.dumps(minimal_manifest, option=orjson.OPT_INDENT_2).decode("utf-8"))
        print(f"✅ 已创建最小化manifest文件: {manifest_path}")
        return True
    except Exception as e:
        print(f"❌ 创建manifest文件失败: {e}")
        return False


def create_complete_manifest(plugin_dir: str, plugin_name: str) -> bool:
    """创建完整的manifest模板文件

    Args:
        plugin_dir: 插件目录
        plugin_name: 插件名称

    Returns:
        bool: 是否创建成功
    """
    manifest_path = os.path.join(plugin_dir, "_manifest.json")

    if os.path.exists(manifest_path):
        print(f"❌ Manifest文件已存在: {manifest_path}")
        return False

    # 创建完整模板
    complete_manifest = {
        "manifest_version": 1,
        "name": plugin_name,
        "version": "1.0.0",
        "description": f"{plugin_name}插件描述",
        "author": {"name": "插件作者", "url": "https://github.com/your-username"},
        "license": "MIT",
        "host_application": {"min_version": "1.0.0", "max_version": "4.0.0"},
        "homepage_url": "https://github.com/your-repo",
        "repository_url": "https://github.com/your-repo",
        "keywords": ["keyword1", "keyword2"],
        "categories": ["Category1"],
        "default_locale": "zh-CN",
        "locales_path": "_locales",
        "plugin_info": {
            "is_built_in": False,
            "plugin_type": "general",
            "components": [{"type": "action", "name": "sample_action", "description": "示例动作组件"}],
        },
    }

    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(orjson.dumps(complete_manifest, option=orjson.OPT_INDENT_2).decode("utf-8"))
        print(f"✅ 已创建完整manifest模板: {manifest_path}")
        print("💡 请根据实际情况修改manifest文件中的内容")
        return True
    except Exception as e:
        print(f"❌ 创建manifest文件失败: {e}")
        return False


def validate_manifest_file(plugin_dir: str) -> bool:
    """验证manifest文件

    Args:
        plugin_dir: 插件目录

    Returns:
        bool: 是否验证通过
    """
    manifest_path = os.path.join(plugin_dir, "_manifest.json")

    if not os.path.exists(manifest_path):
        print(f"❌ 未找到manifest文件: {manifest_path}")
        return False

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = orjson.loads(f.read())

        validator = ManifestValidator()
        is_valid = validator.validate_manifest(manifest_data)

        # 显示验证结果
        print("📋 Manifest验证结果:")
        print(validator.get_validation_report())

        if is_valid:
            print("✅ Manifest文件验证通过")
        else:
            print("❌ Manifest文件验证失败")

        return is_valid

    except orjson.JSONDecodeError as e:
        print(f"❌ Manifest文件格式错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 验证过程中发生错误: {e}")
        return False


def scan_plugins_without_manifest(root_dir: str) -> None:
    """扫描缺少manifest文件的插件

    Args:
        root_dir: 扫描的根目录
    """
    print(f"🔍 扫描目录: {root_dir}")

    plugins_without_manifest = []

    for root, dirs, files in os.walk(root_dir):
        # 跳过隐藏目录和__pycache__
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

        # 检查是否包含plugin.py文件（标识为插件目录）
        if "plugin.py" in files:
            manifest_path = os.path.join(root, "_manifest.json")
            if not os.path.exists(manifest_path):
                plugins_without_manifest.append(root)

    if plugins_without_manifest:
        print(f"❌ 发现 {len(plugins_without_manifest)} 个插件缺少manifest文件:")
        for plugin_dir in plugins_without_manifest:
            plugin_name = os.path.basename(plugin_dir)
            print(f"  - {plugin_name}: {plugin_dir}")
        print("💡 使用 'python manifest_tool.py create-minimal <插件目录>' 创建manifest文件")
    else:
        print("✅ 所有插件都有manifest文件")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="插件Manifest管理工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # 创建最小化manifest命令
    create_minimal_parser = subparsers.add_parser("create-minimal", help="创建最小化manifest文件")
    create_minimal_parser.add_argument("plugin_dir", help="插件目录路径")
    create_minimal_parser.add_argument("--name", help="插件名称")
    create_minimal_parser.add_argument("--description", help="插件描述")
    create_minimal_parser.add_argument("--author", help="插件作者")

    # 创建完整manifest命令
    create_complete_parser = subparsers.add_parser("create-complete", help="创建完整manifest模板")
    create_complete_parser.add_argument("plugin_dir", help="插件目录路径")
    create_complete_parser.add_argument("--name", help="插件名称")

    # 验证manifest命令
    validate_parser = subparsers.add_parser("validate", help="验证manifest文件")
    validate_parser.add_argument("plugin_dir", help="插件目录路径")

    # 扫描插件命令
    scan_parser = subparsers.add_parser("scan", help="扫描缺少manifest的插件")
    scan_parser.add_argument("root_dir", help="扫描的根目录路径")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "create-minimal":
            plugin_name = args.name or os.path.basename(os.path.abspath(args.plugin_dir))
            success = create_minimal_manifest(args.plugin_dir, plugin_name, args.description or "", args.author or "")
            sys.exit(0 if success else 1)

        elif args.command == "create-complete":
            plugin_name = args.name or os.path.basename(os.path.abspath(args.plugin_dir))
            success = create_complete_manifest(args.plugin_dir, plugin_name)
            sys.exit(0 if success else 1)

        elif args.command == "validate":
            success = validate_manifest_file(args.plugin_dir)
            sys.exit(0 if success else 1)

        elif args.command == "scan":
            scan_plugins_without_manifest(args.root_dir)

    except Exception as e:
        print(f"❌ 执行命令时发生错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

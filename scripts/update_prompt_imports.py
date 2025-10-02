"""
更新Prompt类导入脚本
将旧的prompt_builder.Prompt导入更新为unified_prompt.Prompt
"""

import os

# 需要更新的文件列表
files_to_update = [
    "src/person_info/relationship_fetcher.py",
    "src/mood/mood_manager.py",
    "src/mais4u/mais4u_chat/body_emotion_action_manager.py",
    "src/chat/express/expression_learner.py",
    "src/chat/planner_actions/planner.py",
    "src/mais4u/mais4u_chat/s4u_prompt.py",
    "src/chat/message_receive/bot.py",
    "src/chat/replyer/default_generator.py",
    "src/chat/express/expression_selector.py",
    "src/mais4u/mai_think.py",
    "src/mais4u/mais4u_chat/s4u_mood_manager.py",
    "src/plugin_system/core/tool_use.py",
    "src/chat/memory_system/memory_activator.py",
    "src/chat/utils/smart_prompt.py",
]


def update_prompt_imports(file_path):
    """更新文件中的Prompt导入"""
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return False

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # 替换导入语句
    old_import = "from src.chat.utils.prompt_builder import Prompt, global_prompt_manager"
    new_import = "from src.chat.utils.prompt import Prompt, global_prompt_manager"

    if old_import in content:
        new_content = content.replace(old_import, new_import)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"已更新: {file_path}")
        return True
    else:
        print(f"无需更新: {file_path}")
        return False


def main():
    """主函数"""
    updated_count = 0
    for file_path in files_to_update:
        if update_prompt_imports(file_path):
            updated_count += 1

    print(f"\n更新完成！共更新了 {updated_count} 个文件")


if __name__ == "__main__":
    main()

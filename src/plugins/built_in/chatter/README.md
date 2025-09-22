# 亲和力聊天处理器插件

## 概述

这是一个内置的chatter插件，实现了基于亲和力流的智能聊天处理器，具有兴趣度评分和人物关系构建功能。

## 功能特性

- **智能兴趣度评分**: 自动识别和评估用户兴趣话题
- **人物关系系统**: 根据互动历史建立和维持用户关系
- **多聊天类型支持**: 支持私聊和群聊场景
- **插件化架构**: 完全集成到插件系统中

## 组件架构

### BaseChatter (抽象基类)
- 位置: `src/plugin_system/base/base_chatter.py`
- 功能: 定义所有chatter组件的基础接口
- 必须实现的方法: `execute(context: StreamContext) -> dict`

### ChatterManager (管理器)
- 位置: `src/chat/chatter_manager.py`
- 功能: 管理和调度所有chatter组件
- 特性: 自动从插件系统注册和发现chatter组件

### AffinityChatter (具体实现)
- 位置: `src/plugins/built_in/chatter/affinity_chatter.py`
- 功能: 亲和力流聊天处理器的具体实现
- 支持的聊天类型: PRIVATE, GROUP

## 使用方法

### 1. 基本使用

```python
from src.chat.chatter_manager import ChatterManager
from src.chat.planner_actions.action_manager import ActionManager

# 初始化
action_manager = ActionManager()
chatter_manager = ChatterManager(action_manager)

# 处理消息流
result = await chatter_manager.process_stream_context(stream_id, context)
```

### 2. 创建自定义Chatter

```python
from src.plugin_system.base.base_chatter import BaseChatter
from src.plugin_system.base.component_types import ChatType, ComponentType
from src.plugin_system.base.component_types import ChatterInfo

class CustomChatter(BaseChatter):
    chat_types = [ChatType.PRIVATE]  # 只支持私聊

    async def execute(self, context: StreamContext) -> dict:
        # 实现你的聊天逻辑
        return {"success": True, "message": "处理完成"}

# 在插件中注册
async def on_load(self):
    chatter_info = ChatterInfo(
        name="custom_chatter",
        component_type=ComponentType.CHATTER,
        description="自定义聊天处理器",
        enabled=True,
        plugin_name=self.name,
        chat_type_allow=ChatType.PRIVATE
    )

    ComponentRegistry.register_component(
        component_info=chatter_info,
        component_class=CustomChatter
    )
```

## 配置

### 插件配置文件
- 位置: `src/plugins/built_in/chatter/_manifest.json`
- 包含插件信息和组件配置

### 聊天类型
- `PRIVATE`: 私聊
- `GROUP`: 群聊
- `ALL`: 所有类型

## 核心概念

### 1. 兴趣值系统
- 自动识别同类话题
- 兴趣值会根据聊天频率增减
- 支持新话题的自动学习

### 2. 人物关系系统
- 根据互动质量建立关系分
- 不同关系分对应不同的回复风格
- 支持情感化的交流

### 3. 执行流程
1. 接收StreamContext
2. 使用ActionPlanner进行规划
3. 执行相应的Action
4. 返回处理结果

## 扩展开发

### 添加新的Chatter类型
1. 继承BaseChatter类
2. 实现execute方法
3. 在插件中注册组件
4. 配置支持的聊天类型

### 集成现有功能
- 使用ActionPlanner进行动作规划
- 通过ActionManager执行动作
- 利用现有的记忆和知识系统

## 注意事项

1. 所有chatter组件必须实现`execute`方法
2. 插件注册时需要指定支持的聊天类型
3. 组件名称不能包含点号(.)
4. 确保在插件卸载时正确清理资源
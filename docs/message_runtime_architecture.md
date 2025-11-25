# MoFox Bot 消息运行时架构 (MessageRuntime)

本文档描述了 MoFox Bot 使用 `mofox_bus.MessageRuntime` 简化消息处理链条的架构设计。

## 架构概述

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CoreSinkManager                                │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                        MessageRuntime                                ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               ││
│  │  │ before_hook  │→ │   Routes     │→ │ after_hook   │               ││
│  │  │ (预处理/过滤) │  │ (消息路由)   │  │ (后处理)     │               ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘               ││
│  │         ↓                 ↓                 ↓                        ││
│  │  ┌──────────────────────────────────────────────────────────────┐   ││
│  │  │                     error_hook (错误处理)                      │   ││
│  │  └──────────────────────────────────────────────────────────────┘   ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  ┌──────────────────────┐   ┌──────────────────────────────────────┐    │
│  │ InProcessCoreSink    │   │ ProcessCoreSinkServer (子进程适配器)  │    │
│  │ (同进程适配器)        │   │                                      │    │
│  └──────────────────────┘   └──────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
              ↑                                    ↑
              │                                    │
    ┌─────────────────────┐            ┌─────────────────────┐
    │    同进程适配器      │            │     子进程适配器      │
    │ (run_in_subprocess  │            │ (run_in_subprocess   │
    │  = False)           │            │  = True)             │
    └─────────────────────┘            └─────────────────────┘
```

## 核心组件

### 1. CoreSinkManager (`src/common/core_sink_manager.py`)

统一管理 CoreSink 双实例和 MessageRuntime：

```python
from src.common.core_sink_manager import get_core_sink_manager, get_message_runtime

# 获取管理器
manager = get_core_sink_manager()

# 获取 MessageRuntime
runtime = get_message_runtime()

# 发送消息到适配器
await manager.send_outgoing(envelope)
```

### 2. MessageRuntime

`MessageRuntime` 是 mofox_bus 提供的消息路由核心，支持：

- **消息路由**：通过 `add_route()` 或 `@on_message` 装饰器按消息类型路由
- **钩子机制**：`before_hook`（前置处理）、`after_hook`（后置处理）、`error_hook`（错误处理）
- **中间件**：洋葱模型的中间件机制
- **批量处理**：支持 `handle_batch()` 批量处理消息

### 3. MessageHandler (`src/chat/message_receive/message_handler.py`)

将消息处理逻辑注册为 MessageRuntime 的路由和钩子：

```python
class MessageHandler:
    def register_handlers(self, runtime: MessageRuntime) -> None:
        # 注册前置钩子
        runtime.register_before_hook(self._before_hook)
        
        # 注册后置钩子
        runtime.register_after_hook(self._after_hook)
        
        # 注册错误钩子
        runtime.register_error_hook(self._error_hook)
        
        # 注册适配器响应处理器
        runtime.add_route(
            predicate=_is_adapter_response,
            handler=self._handle_adapter_response_route,
            name="adapter_response_handler",
            message_type="adapter_response",
        )
        
        # 注册默认消息处理器
        runtime.add_route(
            predicate=lambda _: True,
            handler=self._handle_normal_message,
            name="default_message_handler",
        )
```

## 消息流向

### 接收消息

```
适配器 → InProcessCoreSink/ProcessCoreSinkServer → CoreSinkManager._dispatch_to_runtime()
       → MessageRuntime.handle_message()
       → before_hook (预处理、过滤)
       → 匹配路由 (adapter_response / normal_message)
       → 执行处理器
       → after_hook (后处理)
```

### 发送消息

```
消息发送请求 → CoreSinkManager.send_outgoing()
           → InProcessCoreSink.push_outgoing()
           → ProcessCoreSinkServer.push_outgoing()
           → 适配器
```

## 钩子功能

### before_hook

在消息路由之前执行，用于：
- 标准化 ID 为字符串
- 检查 echo 消息（自身消息上报）
- 通过抛出 `UserWarning` 跳过消息处理

### after_hook

在消息处理完成后执行，用于：
- 清理工作
- 日志记录

### error_hook

在处理过程中出现异常时执行，用于：
- 区分预期的流程控制（UserWarning）和真正的错误
- 统一异常日志记录

## 路由优先级

1. **明确指定 message_type 的路由**（优先级最高）
2. **事件路由**（基于 event_type）
3. **通用路由**（无 message_type 限制）

## 扩展消息处理

### 注册自定义处理器

```python
from src.common.core_sink_manager import get_message_runtime
from mofox_bus import MessageEnvelope

runtime = get_message_runtime()

# 使用装饰器
@runtime.on_message(message_type="image")
async def handle_image(envelope: MessageEnvelope):
    # 处理图片消息
    pass

# 或使用 add_route
runtime.add_route(
    predicate=lambda env: env.get("platform") == "qq",
    handler=my_handler,
    name="qq_handler",
)
```

### 注册钩子

```python
runtime = get_message_runtime()

# 前置钩子
async def my_before_hook(envelope: MessageEnvelope) -> None:
    # 预处理逻辑
    pass

runtime.register_before_hook(my_before_hook)

# 错误钩子
async def my_error_hook(envelope: MessageEnvelope, exc: BaseException) -> None:
    # 错误处理逻辑
    pass

runtime.register_error_hook(my_error_hook)
```

## 初始化流程

在 `MainSystem.initialize()` 中：

1. 初始化 `CoreSinkManager`（包含 `MessageRuntime`）
2. 获取 `MessageHandler` 并设置 `CoreSinkManager` 引用
3. 调用 `MessageHandler.register_handlers()` 向 `MessageRuntime` 注册处理器和钩子
4. 初始化其他组件

```python
async def initialize(self) -> None:
    # 初始化 CoreSinkManager（包含 MessageRuntime）
    self.core_sink_manager = await initialize_core_sink_manager()
    
    # 获取 MessageHandler 并向 MessageRuntime 注册处理器
    self.message_handler = get_message_handler()
    self.message_handler.set_core_sink_manager(self.core_sink_manager)
    self.message_handler.register_handlers(self.core_sink_manager.runtime)
```

## 优势

1. **简化消息处理链**：不再需要手动管理处理流程，使用声明式路由
2. **更好的可扩展性**：通过 `add_route()` 或装饰器轻松添加新的处理器
3. **统一的错误处理**：通过 `error_hook` 集中处理异常
4. **支持中间件**：可以添加洋葱模型的中间件
5. **更清晰的代码结构**：处理逻辑按类型分离

## 参考

- `packages/mofox-bus/src/mofox_bus/runtime.py` - MessageRuntime 实现
- `src/common/core_sink_manager.py` - CoreSinkManager 实现
- `src/chat/message_receive/message_handler.py` - MessageHandler 实现
- `docs/mofox_bus.md` - MoFox Bus 消息库说明

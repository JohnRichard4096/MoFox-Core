# Phi Plugin for MoFox_Bot

基于MoFox_Bot插件系统的Phigros查分插件，移植自原phi-plugin项目。

## 插件化进展

### ✅ 已完成
1. **基础架构搭建**
   - 创建了完整的插件目录结构
   - 实现了_manifest.json和config.toml配置文件
   - 建立了MoFox_Bot插件系统兼容的基础框架

2. **命令系统迁移**
   - 实现了5个核心命令的PlusCommand适配：
     - `phi help` - 帮助命令
     - `phi bind` - sessionToken绑定命令
     - `phi b30` - Best30查询命令
     - `phi info` - 个人信息查询命令
     - `phi score` - 单曲成绩查询命令

3. **数据管理模块**
   - 创建了PhiDataManager用于数据处理
   - 创建了PhiDatabaseManager用于数据库操作
   - 设计了统一的数据访问接口

4. **配置与元数据**
   - 符合MoFox_Bot规范的manifest文件
   - 支持功能开关的配置文件
   - 完整的插件依赖管理

### 🚧 待实现
1. **核心功能逻辑**
   - Phigros API调用实现
   - sessionToken验证逻辑
   - 存档数据解析处理
   - B30等数据计算算法

2. **数据存储**
   - 用户token数据库存储
   - 曲库数据导入
   - 别名系统迁移

3. **图片生成**
   - B30成绩图片生成
   - 个人信息卡片生成
   - 单曲成绩展示图

4. **高级功能**
   - 更多原phi-plugin命令迁移
   - 数据缓存优化
   - 性能监控

## 目录结构

```
src/plugins/phi_plugin/
├── __init__.py                 # 插件初始化
├── plugin.py                   # 主插件文件
├── _manifest.json              # 插件元数据
├── config.toml                 # 插件配置
├── README.md                   # 本文档
├── commands/                   # 命令实现
│   ├── __init__.py
│   ├── phi_help.py             # 帮助命令
│   ├── phi_bind.py             # 绑定命令
│   ├── phi_b30.py              # B30查询
│   ├── phi_info.py             # 信息查询
│   └── phi_score.py            # 单曲成绩
├── utils/                      # 工具模块
│   ├── __init__.py
│   └── data_manager.py         # 数据管理器
├── data/                       # 数据文件
└── static/                     # 静态资源
```

## 使用方式

### 命令列表
- `/phi help` - 查看帮助
- `/phi bind <token>` - 绑定sessionToken  
- `/phi b30` - 查询Best30成绩
- `/phi info [1|2]` - 查询个人信息
- `/phi score <曲名>` - 查询单曲成绩

### 配置说明
编辑 `config.toml` 文件可以调整：
- 插件启用状态
- API相关设置
- 功能开关

## 技术特点

1. **架构兼容**：完全符合MoFox_Bot插件系统规范
2. **命令适配**：使用PlusCommand系统，支持别名和参数解析
3. **模块化设计**：清晰的模块分离，便于维护和扩展
4. **异步处理**：全面使用async/await进行异步处理
5. **错误处理**：完善的异常处理和用户提示

## 开发说明

目前插件已完成基础架构搭建，可以在MoFox_Bot中正常加载和注册命令。

下一步开发重点：
1. 实现Phigros API调用逻辑
2. 完成数据库存储功能
3. 移植原插件的核心算法
4. 实现图片生成功能

## 原始项目
基于 [phi-plugin](https://github.com/Catrong/phi-plugin) 进行插件化改造。

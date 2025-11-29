# GPT-SoVITS 多情感语音合成插件

基于 GPT-SoVITS 的多情感语音合成插件，支持自动情感分析和语音风格切换，与机器人情绪系统联动实现更自然的语音表达。

## ✨ 特性

- 🎭 **多情感支持**: 预设多种情感风格（开心、悲伤、愤怒、温柔、惊讶等）
- 🤖 **自动情感分析**: 基于关键词或 LLM 自动分析文本情感
- 💭 **情绪系统联动**: 与机器人的情绪系统 (MoodManager) 联动，根据当前情绪选择语音风格
- 🌍 **多语言支持**: 支持中文、日文、粤语、韩文、英文等
- 🔊 **音频后处理**: 可选的空间音效（混响、卷积等）

## 📦 安装

1. 确保已安装 GPT-SoVITS 服务并正常运行
2. 将插件目录复制到 `plugins/` 目录下
3. 安装依赖：
   ```bash
   pip install aiohttp soundfile pedalboard
   ```
4. 启动机器人，插件会自动加载

## ⚙️ 配置

首次启动会在 `config/plugins/gpt_sovits_emotion_tts/config.toml` 生成默认配置文件。

### 基础配置

```toml
[tts]
# GPT-SoVITS 服务器地址
server = "http://127.0.0.1:9880"
# 请求超时时间（秒）
timeout = 180
# 最大文本长度
max_text_length = 1000
```

### 情感风格配置

每种情感需要配置对应的参考音频：

```toml
[[emotion_styles]]
# 情感唯一标识符
emotion_name = "happy"
# 显示名称
display_name = "开心"
# 触发关键词
keywords = ["开心", "高兴", "愉快", "兴奋"]
# 参考音频路径（重要！需要替换为你自己的音频）
refer_wav_path = "path/to/happy_reference.wav"
# 参考音频对应的文本
prompt_text = "这是一段开心的参考音频文本。"
# 参考音频语言
prompt_language = "zh"
# GPT 模型路径（可选，留空使用全局配置）
gpt_weights = ""
# SoVITS 模型路径（可选，留空使用全局配置）
sovits_weights = ""
# 语速因子
speed_factor = 1.05
```

### 预设情感

插件预设了以下情感风格：

| 情感名称 | 显示名称 | 说明 |
|---------|---------|------|
| neutral | 平静 | 默认情感 |
| happy | 开心 | 愉快、兴奋 |
| sad | 悲伤 | 难过、失落 |
| angry | 愤怒 | 生气、不满 |
| surprised | 惊讶 | 意外、吃惊 |
| fearful | 害怕 | 紧张、焦虑 |
| disgusted | 厌恶 | 反感、讨厌 |
| gentle | 温柔 | 撒娇、甜美 |
| serious | 严肃 | 认真、正经 |

## 🎮 使用方法

### 命令方式

```
/etts <文本>                    # 自动分析情感
/etts <文本> --emotion happy    # 指定情感
/etts list                      # 查看可用情感
```

**示例:**
```
/etts 今天天气真好啊
/etts 我好开心呀！ --emotion happy
/etts 怎么会这样... --emotion sad
```

### Action 方式

插件会自动注册 Action 组件，LLM 可以在以下场景触发语音合成：

- 用户请求语音回复（"发个语音"、"用语音说"等）
- 表达特殊情感的场景
- 角色扮演、讲故事等场景
- 随机触发（20% 概率）

LLM 可以通过 `action_parameters` 指定：
- `tts_text`: 要合成的文本
- `emotion`: 情感风格（可选，不指定则自动分析）
- `text_language`: 语言模式（可选）

## 🔧 高级配置

### 情感分析

```toml
[emotion_analysis]
# 是否启用自动情感分析
enabled = true
# 是否使用机器人情绪系统的情绪状态
use_bot_mood = true
# 情感分析模型（留空使用默认）
model = ""
```

### 空间音效

```toml
[spatial_effects]
enabled = false
reverb_enabled = false
room_size = 0.2
damping = 0.6
wet_level = 0.3
dry_level = 0.8
```

### TTS 高级参数

```toml
[tts_advanced]
top_k = 9
top_p = 0.8
temperature = 0.8
batch_size = 6
text_split_method = "cut5"
repetition_penalty = 1.4
```

## 📝 准备参考音频

为获得最佳效果，每种情感需要准备对应的参考音频：

1. **录制要求**:
   - 时长: 3-10 秒
   - 采样率: 建议 32kHz 或 44.1kHz
   - 格式: WAV
   - 环境: 安静、无混响

2. **内容要求**:
   - 音频内容要与目标情感一致
   - 清晰的语音，适当的语气
   - 准确记录对应的文本

3. **示例**:
   - 开心: 一段笑着说话的音频
   - 悲伤: 一段低沉、缓慢的音频
   - 愤怒: 一段语调激烈的音频
   - 温柔: 一段轻柔、甜美的音频

## 🔍 故障排除

### 语音合成失败

1. 检查 GPT-SoVITS 服务是否正常运行
2. 检查配置文件中的服务器地址是否正确
3. 检查参考音频路径是否存在
4. 查看日志获取详细错误信息

### 情感识别不准确

1. 检查情感配置中的关键词是否合理
2. 尝试启用 LLM 情感分析
3. 调整情感分析配置

### 音质问题

1. 检查参考音频质量
2. 调整 TTS 高级参数
3. 尝试启用/禁用空间音效

## 📄 许可证

MIT License

## 🙏 致谢

- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) - 强大的语音合成框架
- MoFox-Core - 机器人核心框架

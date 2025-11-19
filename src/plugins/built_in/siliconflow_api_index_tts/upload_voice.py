#!/usr/bin/env python3
"""
SiliconFlow IndexTTS Voice Upload Tool
用于上传参考音频文件并获取voice_id的工具脚本
"""

import asyncio
import base64
import logging
import sys
from pathlib import Path

import aiohttp
import toml


# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class VoiceUploader:
    """语音上传器"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.upload_url = "https://api.siliconflow.cn/v1/uploads/audio/voice"
        
    async def upload_audio(self, audio_path: str) -> str:
        """
        上传音频文件并获取voice_id
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            voice_id: 返回的语音ID
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        # 读取音频文件并转换为base64
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        # 准备请求数据
        request_data = {
            "file": audio_base64,
            "filename": audio_path
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"正在上传音频文件: {audio_path}")
        logger.info(f"文件大小: {len(audio_data)} bytes")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.upload_url,
                headers=headers,
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    voice_id = result.get("id")
                    if voice_id:
                        logger.info(f"上传成功！获取到voice_id: {voice_id}")
                        return voice_id
                    else:
                        logger.error(f"上传响应中没有找到voice_id: {result}")
                        raise Exception("上传响应中没有找到voice_id")
                else:
                    error_text = await response.text()
                    logger.error(f"上传失败 (状态码: {response.status}): {error_text}")
                    raise Exception(f"上传失败: {error_text}")


def load_config(config_path: Path) -> dict:
    """加载配置文件"""
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return toml.load(f)
    return {}


def save_config(config_path: Path, config: dict):
    """保存配置文件"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        toml.dump(config, f)


async def main():
    """主函数"""
    if len(sys.argv) != 2:
        print("用法: python upload_voice.py <音频文件路径>")
        print("示例: python upload_voice.py refer.mp3")
        sys.exit(1)
    
    audio_file = sys.argv[1]
    
    # 获取插件目录
    plugin_dir = Path(__file__).parent
    
    # 加载全局配置获取API key
    bot_dir = plugin_dir.parents[2]  # 回到Bot目录
    global_config_path = bot_dir / "config" / "model_config.toml"
    
    if not global_config_path.exists():
        logger.error(f"全局配置文件不存在: {global_config_path}")
        logger.error("请确保Bot/config/model_config.toml文件存在并配置了SiliconFlow API密钥")
        sys.exit(1)
    
    global_config = load_config(global_config_path)
    
    # 从api_providers中查找SiliconFlow的API密钥
    api_key = None
    api_providers = global_config.get("api_providers", [])
    for provider in api_providers:
        if provider.get("name") == "SiliconFlow":
            api_key = provider.get("api_key")
            break
    
    if not api_key:
        logger.error("在全局配置中未找到SiliconFlow API密钥")
        logger.error("请在Bot/config/model_config.toml中添加SiliconFlow的api_providers配置:")
        logger.error("[[api_providers]]")
        logger.error("name = \"SiliconFlow\"")
        logger.error("base_url = \"https://api.siliconflow.cn/v1\"")
        logger.error("api_key = \"your_api_key_here\"")
        logger.error("client_type = \"openai\"")
        sys.exit(1)
    
    try:
        # 创建上传器并上传音频
        uploader = VoiceUploader(api_key)
        voice_id = await uploader.upload_audio(audio_file)
        
        # 更新插件配置
        plugin_config_path = plugin_dir / "config.toml"
        plugin_config = load_config(plugin_config_path)
        
        if "synthesis" not in plugin_config:
            plugin_config["synthesis"] = {}
        
        plugin_config["synthesis"]["voice_id"] = voice_id
        
        save_config(plugin_config_path, plugin_config)
        
        logger.info(f"配置已更新！voice_id已保存到: {plugin_config_path}")
        logger.info("现在可以使用SiliconFlow IndexTTS插件了！")
        
    except Exception as e:
        logger.error(f"上传失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
#!/usr/bin/env python3
"""
Bilibili 工具基础模块
提供 B 站视频信息获取和视频分析功能
"""

import asyncio
import re
from typing import Any

import aiohttp

from src.chat.utils.utils_video import get_video_analyzer
from src.common.logger import get_logger

logger = get_logger("bilibili_tool")


class BilibiliVideoAnalyzer:
    """哔哩哔哩视频分析器，集成视频下载和AI分析功能"""

    def __init__(self):
        self.video_analyzer = get_video_analyzer()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        }

    def extract_bilibili_url(self, text: str) -> str | None:
        """从文本中提取哔哩哔哩视频链接"""
        # 哔哩哔哩短链接模式
        short_pattern = re.compile(r"https?://b23\.tv/[\w]+", re.IGNORECASE)
        # 哔哩哔哩完整链接模式
        full_pattern = re.compile(r"https?://(?:www\.)?bilibili\.com/video/(?:BV[\w]+|av\d+)", re.IGNORECASE)

        # 先匹配短链接
        short_match = short_pattern.search(text)
        if short_match:
            return short_match.group(0)

        # 再匹配完整链接
        full_match = full_pattern.search(text)
        if full_match:
            return full_match.group(0)

        return None

    async def get_video_info(self, url: str) -> dict[str, Any] | None:
        """获取哔哩哔哩视频基本信息"""
        try:
            logger.info(f"🔍 解析视频URL: {url}")

            # 如果是短链接，先解析为完整链接
            if "b23.tv" in url:
                logger.info("🔗 检测到短链接，正在解析...")
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=self.headers, allow_redirects=True) as response:
                        url = str(response.url)
                        logger.info(f"✅ 短链接解析完成: {url}")

            # 提取BV号或AV号
            bv_match = re.search(r"BV([\w]+)", url)
            av_match = re.search(r"av(\d+)", url)

            if bv_match:
                bvid = f"BV{bv_match.group(1)}"
                api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
                logger.info(f"📺 提取到BV号: {bvid}")
            elif av_match:
                aid = av_match.group(1)
                api_url = f"https://api.bilibili.com/x/web-interface/view?aid={aid}"
                logger.info(f"📺 提取到AV号: av{aid}")
            else:
                logger.error("❌ 无法从URL中提取视频ID")
                return None

            # 获取视频信息
            logger.info("📡 正在获取视频信息...")
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url, headers=self.headers) as response:
                    if response.status != 200:
                        logger.error(f"❌ API请求失败，状态码: {response.status}")
                        return None
                    data = await response.json()

            if data.get("code") != 0:
                error_msg = data.get("message", "未知错误")
                logger.error(f"❌ B站API返回错误: {error_msg} (code: {data.get('code')})")
                return None

            video_data = data["data"]

            # 验证必要字段
            if not video_data.get("title"):
                logger.error("❌ 视频数据不完整，缺少标题")
                return None

            result = {
                "title": video_data.get("title", ""),
                "desc": video_data.get("desc", ""),
                "duration": video_data.get("duration", 0),
                "view": video_data.get("stat", {}).get("view", 0),
                "like": video_data.get("stat", {}).get("like", 0),
                "coin": video_data.get("stat", {}).get("coin", 0),
                "favorite": video_data.get("stat", {}).get("favorite", 0),
                "share": video_data.get("stat", {}).get("share", 0),
                "owner": video_data.get("owner", {}).get("name", ""),
                "pubdate": video_data.get("pubdate", 0),
                "aid": video_data.get("aid"),
                "bvid": video_data.get("bvid"),
                "cid": video_data.get("cid")
                or (video_data.get("pages", [{}])[0].get("cid") if video_data.get("pages") else None),
            }

            logger.info(f"✅ 视频信息获取成功: {result['title']}")
            return result

        except asyncio.TimeoutError:
            logger.error("❌ 获取视频信息超时")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"❌ 网络请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ 获取哔哩哔哩视频信息时发生未知错误: {e}")
            logger.exception("详细错误信息:")
            return None

    async def get_video_stream_url(self, aid: int, cid: int) -> str | None:
        """获取视频流URL"""
        try:
            logger.info(f"🎥 获取视频流URL: aid={aid}, cid={cid}")

            # 构建播放信息API请求
            api_url = f"https://api.bilibili.com/x/player/playurl?avid={aid}&cid={cid}&qn=80&type=&otype=json&fourk=1&fnver=0&fnval=4048&session="

            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url, headers=self.headers) as response:
                    if response.status != 200:
                        logger.error(f"❌ 播放信息API请求失败，状态码: {response.status}")
                        return None
                    data = await response.json()

            if data.get("code") != 0:
                error_msg = data.get("message", "未知错误")
                logger.error(f"❌ 获取播放信息失败: {error_msg} (code: {data.get('code')})")
                return None

            play_data = data["data"]

            # 尝试获取DASH格式的视频流
            if "dash" in play_data and play_data["dash"].get("video"):
                videos = play_data["dash"]["video"]
                logger.info(f"🎬 找到 {len(videos)} 个DASH视频流")

                # 选择最高质量的视频流
                video_stream = max(videos, key=lambda x: x.get("bandwidth", 0))
                stream_url = video_stream.get("baseUrl") or video_stream.get("base_url")

                if stream_url:
                    logger.info(f"✅ 获取到DASH视频流URL (带宽: {video_stream.get('bandwidth', 0)})")
                    return stream_url

            # 降级到FLV格式
            if play_data.get("durl"):
                logger.info("📹 使用FLV格式视频流")
                stream_url = play_data["durl"][0].get("url")
                if stream_url:
                    logger.info("✅ 获取到FLV视频流URL")
                    return stream_url

            logger.error("❌ 未找到可用的视频流")
            return None

        except asyncio.TimeoutError:
            logger.error("❌ 获取视频流URL超时")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"❌ 网络请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ 获取视频流URL时发生未知错误: {e}")
            logger.exception("详细错误信息:")
            return None

    async def download_video_bytes(self, stream_url: str, max_size_mb: int = 100) -> bytes | None:
        """下载视频字节数据

        Args:
            stream_url: 视频流URL
            max_size_mb: 最大下载大小限制（MB），默认100MB

        Returns:
            视频字节数据或None
        """
        try:
            logger.info(f"📥 开始下载视频: {stream_url[:50]}...")

            # 设置超时和大小限制
            timeout = aiohttp.ClientTimeout(total=300, connect=30)  # 5分钟总超时，30秒连接超时

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(stream_url, headers=self.headers) as response:
                    if response.status != 200:
                        logger.error(f"❌ 下载失败，HTTP状态码: {response.status}")
                        return None

                    # 检查内容长度
                    content_length = response.headers.get("content-length")
                    if content_length:
                        size_mb = int(content_length) / 1024 / 1024
                        if size_mb > max_size_mb:
                            logger.error(f"❌ 视频文件过大: {size_mb:.1f}MB > {max_size_mb}MB")
                            return None
                        logger.info(f"📊 预计下载大小: {size_mb:.1f}MB")

                    # 分块下载并监控大小
                    video_bytes = bytearray()
                    downloaded_mb = 0

                    async for chunk in response.content.iter_chunked(8192):  # 8KB块
                        video_bytes.extend(chunk)
                        downloaded_mb = len(video_bytes) / 1024 / 1024

                        # 检查大小限制
                        if downloaded_mb > max_size_mb:
                            logger.error(f"❌ 下载中止，文件过大: {downloaded_mb:.1f}MB > {max_size_mb}MB")
                            return None

                    final_size_mb = len(video_bytes) / 1024 / 1024
                    logger.info(f"✅ 视频下载完成，实际大小: {final_size_mb:.2f}MB")
                    return bytes(video_bytes)

        except asyncio.TimeoutError:
            logger.error("❌ 下载超时")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"❌ 网络请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ 下载视频时发生未知错误: {e}")
            logger.exception("详细错误信息:")
            return None

    async def analyze_bilibili_video(self, url: str, prompt: str = None) -> dict[str, Any]:
        """分析哔哩哔哩视频并返回详细信息和AI分析结果"""
        try:
            logger.info(f"🎬 开始分析哔哩哔哩视频: {url}")

            # 1. 获取视频基本信息
            video_info = await self.get_video_info(url)
            if not video_info:
                logger.error("❌ 无法获取视频基本信息")
                return {"error": "无法获取视频信息"}

            logger.info(f"📺 视频标题: {video_info['title']}")
            logger.info(f"👤 UP主: {video_info['owner']}")
            logger.info(f"⏱️ 时长: {video_info['duration']}秒")

            # 2. 获取视频流URL
            stream_url = await self.get_video_stream_url(video_info["aid"], video_info["cid"])
            if not stream_url:
                logger.warning("⚠️ 无法获取视频流，仅返回基本信息")
                return {"video_info": video_info, "error": "无法获取视频流，仅返回基本信息"}

            # 3. 下载视频
            video_bytes = await self.download_video_bytes(stream_url)
            if not video_bytes:
                logger.warning("⚠️ 视频下载失败，仅返回基本信息")
                return {"video_info": video_info, "error": "视频下载失败，仅返回基本信息"}

            # 4. 构建增强的元数据信息
            enhanced_metadata = {
                "title": video_info["title"],
                "uploader": video_info["owner"],
                "duration": video_info["duration"],
                "view_count": video_info["view"],
                "like_count": video_info["like"],
                "description": video_info["desc"],
                "bvid": video_info["bvid"],
                "aid": video_info["aid"],
                "file_size": len(video_bytes),
                "source": "bilibili",
            }

            # 5. 使用新的视频分析API，传递完整的元数据
            logger.info("🤖 开始AI视频分析...")
            analysis_result = await self.video_analyzer.analyze_video_from_bytes(
                video_bytes=video_bytes,
                filename=f"{video_info['title']}.mp4",
                prompt=prompt,  # 使用新API的prompt参数而不是user_question
            )

            # 6. 检查分析结果
            if not analysis_result or not analysis_result.get("summary"):
                logger.error("❌ 视频分析失败或返回空结果")
                return {"video_info": video_info, "error": "视频分析失败，仅返回基本信息"}

            # 7. 格式化返回结果
            duration_str = f"{video_info['duration'] // 60}分{video_info['duration'] % 60}秒"

            result = {
                "video_info": {
                    "标题": video_info["title"],
                    "UP主": video_info["owner"],
                    "时长": duration_str,
                    "播放量": f"{video_info['view']:,}",
                    "点赞": f"{video_info['like']:,}",
                    "投币": f"{video_info['coin']:,}",
                    "收藏": f"{video_info['favorite']:,}",
                    "转发": f"{video_info['share']:,}",
                    "简介": video_info["desc"][:200] + "..." if len(video_info["desc"]) > 200 else video_info["desc"],
                },
                "ai_analysis": analysis_result.get("summary", ""),
                "success": True,
                "metadata": enhanced_metadata,  # 添加元数据信息
            }

            logger.info("✅ 哔哩哔哩视频分析完成")
            return result

        except Exception as e:
            error_msg = f"分析哔哩哔哩视频时发生异常: {e!s}"
            logger.error(f"❌ {error_msg}")
            logger.exception("详细错误信息:")  # 记录完整的异常堆栈
            return {"error": f"分析失败: {e!s}"}


# 全局实例
_bilibili_analyzer = None


def get_bilibili_analyzer() -> BilibiliVideoAnalyzer:
    """获取哔哩哔哩视频分析器实例（单例模式）"""
    global _bilibili_analyzer
    if _bilibili_analyzer is None:
        _bilibili_analyzer = BilibiliVideoAnalyzer()
    return _bilibili_analyzer

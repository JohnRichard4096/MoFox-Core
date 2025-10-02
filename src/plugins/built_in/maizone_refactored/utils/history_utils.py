"""
历史记录工具模块
提供用于获取QQ空间发送历史的功能。
"""

import os
from pathlib import Path
from typing import Any

import orjson
import requests

from src.common.logger import get_logger

logger = get_logger("MaiZone.HistoryUtils")


class _CookieManager:
    """简化的Cookie管理类，仅用于读取历史记录"""

    @staticmethod
    def get_cookie_file_path(uin: str) -> str:
        current_dir = Path(__file__).resolve().parent.parent
        cookie_dir = current_dir / "cookies"
        cookie_dir.mkdir(exist_ok=True)
        return str(cookie_dir / f"cookies-{uin}.json")

    @staticmethod
    def load_cookies(qq_account: str) -> dict[str, str] | None:
        cookie_file = _CookieManager.get_cookie_file_path(qq_account)
        if os.path.exists(cookie_file):
            try:
                with open(cookie_file, encoding="utf-8") as f:
                    return orjson.loads(f.read())
            except Exception as e:
                logger.error(f"加载Cookie文件失败: {e}")
        return None


class _SimpleQZoneAPI:
    """极简的QZone API客户端，仅用于获取说说列表"""

    LIST_URL = "https://user.qzone.qq.com/proxy/domain/taotao.qq.com/cgi-bin/emotion_cgi_msglist_v6"

    def __init__(self, cookies_dict: dict[str, str] | None = None):
        self.cookies = cookies_dict or {}
        self.gtk2 = ""
        p_skey = self.cookies.get("p_skey") or self.cookies.get("p_skey".upper())
        if p_skey:
            self.gtk2 = self._generate_gtk(p_skey)

    def _generate_gtk(self, skey: str) -> str:
        hash_val = 5381
        for char in skey:
            hash_val += (hash_val << 5) + ord(char)
        return str(hash_val & 2147483647)

    def get_feed_list(self, target_qq: str, num: int) -> list[dict[str, Any]]:
        try:
            params = {
                "g_tk": self.gtk2,
                "uin": target_qq,
                "ftype": 0,
                "sort": 0,
                "pos": 0,
                "num": num,
                "replynum": 100,
                "callback": "_preloadCallback",
                "code_version": 1,
                "format": "jsonp",
                "need_comment": 1,
            }
            res = requests.get(self.LIST_URL, params=params, cookies=self.cookies, timeout=10)

            if res.status_code != 200:
                return []

            data = res.text
            json_str = data[len("_preloadCallback(") : -2] if data.startswith("_preloadCallback(") else data
            json_data = orjson.loads(json_str)

            return json_data.get("msglist", [])
        except Exception as e:
            logger.error(f"获取说说列表失败: {e}")
            return []


async def get_send_history(qq_account: str) -> str:
    """
    获取指定QQ账号最近的说说发送历史。

    :param qq_account: 需要查询的QQ账号。
    :return: 格式化后的历史记录字符串，如果失败则返回空字符串。
    """
    try:
        cookies = _CookieManager.load_cookies(qq_account)
        if not cookies:
            return ""

        qzone_api = _SimpleQZoneAPI(cookies)
        feeds_list = qzone_api.get_feed_list(target_qq=qq_account, num=5)

        if not feeds_list:
            return ""

        history_lines = ["==================="]
        for feed in feeds_list:
            if not isinstance(feed, dict):
                continue

            content = feed.get("content", "")
            rt_con_data = feed.get("rt_con")
            rt_con = rt_con_data.get("content", "") if isinstance(rt_con_data, dict) else ""

            line = f"\n内容：'{content}'"
            if rt_con:
                line += f"\n(转发自: '{rt_con}')"
            line += "\n==================="
            history_lines.append(line)

        return "".join(history_lines)
    except Exception as e:
        logger.error(f"获取发送历史失败: {e}")
        return ""

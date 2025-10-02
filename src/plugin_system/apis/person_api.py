"""个人信息API模块

提供个人信息查询功能，用于插件获取用户相关信息
使用方式：
    from src.plugin_system.apis import person_api
    person_id = person_api.get_person_id("qq", 123456)
    value = await person_api.get_person_value(person_id, "nickname")
"""

from typing import Any

from src.common.logger import get_logger
from src.person_info.person_info import PersonInfoManager, get_person_info_manager

logger = get_logger("person_api")


# =============================================================================
# 个人信息API函数
# =============================================================================


def get_person_id(platform: str, user_id: int | str) -> str:
    """根据平台和用户ID获取person_id

    Args:
        platform: 平台名称，如 "qq", "telegram" 等
        user_id: 用户ID

    Returns:
        str: 唯一的person_id（MD5哈希值）

    示例:
        person_id = person_api.get_person_id("qq", 123456)
    """
    try:
        return Person(platform=platform, user_id=str(user_id)).person_id
    except Exception as e:
        logger.error(f"[PersonAPI] 获取person_id失败: platform={platform}, user_id={user_id}, error={e}")
        return ""


async def get_person_value(person_id: str, field_name: str, default: Any = None) -> Any:
    """根据person_id和字段名获取某个值

    Args:
        person_id: 用户的唯一标识ID
        field_name: 要获取的字段名，如 "nickname", "impression" 等
        default: 当字段不存在或获取失败时返回的默认值

    Returns:
        Any: 字段值或默认值

    示例:
        nickname = await person_api.get_person_value(person_id, "nickname", "未知用户")
        impression = await person_api.get_person_value(person_id, "impression")
    """
    try:
        person = Person(person_id=person_id)
        value = getattr(person, field_name)
        return value if value is not None else default
    except Exception as e:
        logger.error(f"[PersonAPI] 获取用户信息失败: person_id={person_id}, field={field_name}, error={e}")
        return default


async def get_person_values(person_id: str, field_names: list, default_dict: dict | None = None) -> dict:
    """批量获取用户信息字段值

    Args:
        person_id: 用户的唯一标识ID
        field_names: 要获取的字段名列表
        default_dict: 默认值字典，键为字段名，值为默认值

    Returns:
        dict: 字段名到值的映射字典

    示例:
        values = await person_api.get_person_values(
            person_id,
            ["nickname", "impression", "know_times"],
            {"nickname": "未知用户", "know_times": 0}
        )
    """
    try:
        person_info_manager = get_person_info_manager()
        values = await person_info_manager.get_values(person_id, field_names)

        # 如果获取成功，返回结果
        if values:
            return values

        # 如果获取失败，构建默认值字典
        result = {}
        if default_dict:
            for field in field_names:
                result[field] = default_dict.get(field, None)
        else:
            for field in field_names:
                result[field] = None

        return result

    except Exception as e:
        logger.error(f"[PersonAPI] 批量获取用户信息失败: person_id={person_id}, fields={field_names}, error={e}")
        # 返回默认值字典
        result = {}
        if default_dict:
            for field in field_names:
                result[field] = default_dict.get(field, None)
        else:
            for field in field_names:
                result[field] = None
        return result


async def is_person_known(platform: str, user_id: int) -> bool:
    """判断是否认识某个用户

    Args:
        platform: 平台名称
        user_id: 用户ID

    Returns:
        bool: 是否认识该用户

    示例:
        known = await person_api.is_person_known("qq", 123456)
    """
    try:
        person_info_manager = get_person_info_manager()
        return await person_info_manager.is_person_known(platform, user_id)
    except Exception as e:
        logger.error(f"[PersonAPI] 检查用户是否已知失败: platform={platform}, user_id={user_id}, error={e}")
        return False


async def get_person_id_by_name(person_name: str) -> str:
    """根据用户名获取person_id

    Args:
        person_name: 用户名

    Returns:
        str: person_id，如果未找到返回空字符串

    示例:
        person_id = person_api.get_person_id_by_name("张三")
    """
    try:
        person_info_manager = get_person_info_manager()
        return await person_info_manager.get_person_id_by_person_name(person_name)
    except Exception as e:
        logger.error(f"[PersonAPI] 根据用户名获取person_id失败: person_name={person_name}, error={e}")
        return ""

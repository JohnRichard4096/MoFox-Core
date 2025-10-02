from dataclasses import MISSING, dataclass, fields
from typing import Any, Literal, TypeVar, get_args, get_origin

from pydantic import BaseModel, ValidationError
from typing_extensions import Self

T = TypeVar("T", bound="ConfigBase")

TOML_DICT_TYPE = {
    int,
    float,
    str,
    bool,
    list,
    dict,
}


@dataclass
class ConfigBase:
    """配置类的基类"""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """从字典加载配置字段"""
        if not isinstance(data, dict):
            raise TypeError(f"Expected a dictionary, got {type(data).__name__}")

        init_args: dict[str, Any] = {}

        for f in fields(cls):
            field_name = f.name

            if field_name.startswith("_"):
                # 跳过以 _ 开头的字段
                continue

            if field_name not in data:
                if f.default is not MISSING or f.default_factory is not MISSING:
                    # 跳过未提供且有默认值/默认构造方法的字段
                    continue
                else:
                    raise ValueError(f"Missing required field: '{field_name}'")

            value = data[field_name]
            field_type = f.type

            try:
                init_args[field_name] = cls._convert_field(value, field_type)  # type: ignore
            except TypeError as e:
                raise TypeError(f"Field '{field_name}' has a type error: {e}") from e
            except Exception as e:
                raise RuntimeError(f"Failed to convert field '{field_name}' to target type: {e}") from e

        return cls()

    @classmethod
    def _convert_field(cls, value: Any, field_type: type[Any]) -> Any:
        """
        转换字段值为指定类型

        1. 对于嵌套的 dataclass，递归调用相应的 from_dict 方法
        2. 对于泛型集合类型（list, set, tuple），递归转换每个元素
        3. 对于基础类型（int, str, float, bool），直接转换
        4. 对于其他类型，尝试直接转换，如果失败则抛出异常
        """

        # 如果是嵌套的 dataclass，递归调用 from_dict 方法
        if isinstance(field_type, type) and issubclass(field_type, ConfigBase):
            if not isinstance(value, dict):
                raise TypeError(f"Expected a dictionary for {field_type.__name__}, got {type(value).__name__}")
            return field_type.from_dict(value)

        # 处理泛型集合类型（list, set, tuple）
        field_origin_type = get_origin(field_type)
        field_type_args = get_args(field_type)

        if field_origin_type in {list, set, tuple}:
            # 检查提供的value是否为list
            if not isinstance(value, list):
                raise TypeError(f"Expected an list for {field_type.__name__}, got {type(value).__name__}")

            if field_origin_type is list:
                # 如果列表元素类型是ConfigBase的子类，则对每个元素调用from_dict
                if (
                    field_type_args
                    and isinstance(field_type_args[0], type)
                    and issubclass(field_type_args[0], ConfigBase)
                ):
                    return [field_type_args[0].from_dict(item) for item in value]
                return [cls._convert_field(item, field_type_args[0]) for item in value]
            elif field_origin_type is set:
                return {cls._convert_field(item, field_type_args[0]) for item in value}
            elif field_origin_type is tuple:
                # 检查提供的value长度是否与类型参数一致
                if len(value) != len(field_type_args):
                    raise TypeError(
                        f"Expected {len(field_type_args)} items for {field_type.__name__}, got {len(value)}"
                    )
                return tuple(cls._convert_field(item, arg) for item, arg in zip(value, field_type_args, strict=False))

        if field_origin_type is dict:
            # 检查提供的value是否为dict
            if not isinstance(value, dict):
                raise TypeError(f"Expected a dictionary for {field_type.__name__}, got {type(value).__name__}")

            # 检查字典的键值类型
            if len(field_type_args) != 2:
                raise TypeError(f"Expected a dictionary with two type arguments for {field_type.__name__}")
            key_type, value_type = field_type_args

            return {cls._convert_field(k, key_type): cls._convert_field(v, value_type) for k, v in value.items()}

        # 处理基础类型，例如 int, str 等
        if field_origin_type is type(None) and value is None:  # 处理Optional类型
            return None

        # 处理Literal类型
        if field_origin_type is Literal or get_origin(field_type) is Literal:
            # 获取Literal的允许值
            allowed_values = get_args(field_type)
            if value in allowed_values:
                return value
            else:
                raise TypeError(f"Value '{value}' is not in allowed values {allowed_values} for Literal type")

        if field_type is Any or isinstance(value, field_type):
            return value

        # 其他类型，尝试直接转换
        try:
            return field_type(value)
        except (ValueError, TypeError) as e:
            raise TypeError(f"Cannot convert {type(value).__name__} to {field_type.__name__}") from e

    def __str__(self):
        """返回配置类的字符串表示"""
        return f"{self.__class__.__name__}({', '.join(f'{f.name}={getattr(self, f.name)}' for f in fields(self))})"


class ValidatedConfigBase(BaseModel):
    """带验证的配置基类，继承自Pydantic BaseModel"""

    model_config = {
        "extra": "allow",  # 允许额外字段
        "validate_assignment": True,  # 验证赋值
        "arbitrary_types_allowed": True,  # 允许任意类型
        "strict": True,  # 如果设为 True 会完全禁用类型转换
    }

    @classmethod
    def from_dict(cls, data: dict):
        """兼容原有的from_dict方法，增强错误信息"""
        try:
            return cls.model_validate(data)
        except ValidationError as e:
            enhanced_message = cls._create_enhanced_error_message(e, data)

            raise ValueError(enhanced_message) from e

    @classmethod
    def _create_enhanced_error_message(cls, e: ValidationError, data: dict) -> str:
        """创建增强的错误信息"""
        enhanced_messages = []

        for error in e.errors():
            error_type = error.get("type", "")
            field_path = error.get("loc", ())
            input_value = error.get("input")

            # 构建字段路径字符串
            field_path_str = ".".join(str(p) for p in field_path)

            # 处理字符串类型错误
            if error_type == "string_type" and len(field_path) >= 2:
                parent_field = field_path[0]
                element_index = field_path[1]

                # 尝试获取父字段的类型信息
                parent_field_info = cls.model_fields.get(parent_field)

                if parent_field_info and hasattr(parent_field_info, "annotation"):
                    expected_type = parent_field_info.annotation

                    # 获取实际的父字段值
                    actual_parent_value = data.get(parent_field)

                    # 检查是否是列表类型错误
                    if get_origin(expected_type) is list and isinstance(actual_parent_value, list):
                        list_element_type = get_args(expected_type)[0] if get_args(expected_type) else str
                        actual_item_type = type(input_value).__name__
                        expected_element_name = getattr(list_element_type, "__name__", str(list_element_type))

                        enhanced_messages.append(
                            f"字段 '{field_path_str}' 类型错误: "
                            f"期待类型 List[{expected_element_name}]，"
                            f"但列表中第 {element_index} 个元素类型为 {actual_item_type} (值: {input_value})"
                        )
                    else:
                        # 其他嵌套字段错误
                        actual_name = type(input_value).__name__
                        enhanced_messages.append(
                            f"字段 '{field_path_str}' 类型错误: "
                            f"期待字符串类型，实际类型 {actual_name} (值: {input_value})"
                        )
                else:
                    # 回退到原始错误信息
                    enhanced_messages.append(f"字段 '{field_path_str}': {error.get('msg', str(error))}")

            # 处理缺失字段错误
            elif error_type == "missing":
                enhanced_messages.append(f"缺少必需字段: '{field_path_str}'")

            # 处理模型类型错误
            elif error_type in ["model_type", "dict_type", "is_instance_of"]:
                field_name = field_path[0] if field_path else "unknown"
                field_info = cls.model_fields.get(field_name)

                if field_info and hasattr(field_info, "annotation"):
                    expected_type = field_info.annotation
                    expected_name = getattr(expected_type, "__name__", str(expected_type))
                    actual_name = type(input_value).__name__

                    enhanced_messages.append(
                        f"字段 '{field_name}' 类型错误: "
                        f"期待类型 {expected_name}，实际类型 {actual_name} (值: {input_value})"
                    )
                else:
                    enhanced_messages.append(f"字段 '{field_path_str}': {error.get('msg', str(error))}")

            # 处理其他类型错误
            else:
                enhanced_messages.append(f"字段 '{field_path_str}': {error.get('msg', str(error))}")

        return "配置验证失败：\n" + "\n".join(f"  - {msg}" for msg in enhanced_messages)

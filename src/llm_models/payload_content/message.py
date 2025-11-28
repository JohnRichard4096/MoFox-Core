import base64
import io
from enum import Enum

from PIL import Image

# 设计这系列类的目的是为未来可能的扩展做准备


class RoleType(Enum):
    System = "system"
    User = "user"
    Assistant = "assistant"
    Tool = "tool"


SUPPORTED_IMAGE_FORMATS = ["jpg", "jpeg", "png", "webp", "gif"]  # openai支持的图片格式


class Message:
    def __init__(
        self,
        role: RoleType,
        content: str | list[tuple[str, str] | str],
        tool_call_id: str | None = None,
    ):
        """
        初始化消息对象
        （不应直接修改Message类，而应使用MessageBuilder类来构建对象）
        """
        self.role: RoleType = role
        self.content: str | list[tuple[str, str] | str] = content
        self.tool_call_id: str | None = tool_call_id


class MessageBuilder:
    def __init__(self):
        self.__role: RoleType = RoleType.User
        self.__content: list[tuple[str, str] | str] = []
        self.__tool_call_id: str | None = None

    def set_role(self, role: RoleType = RoleType.User) -> "MessageBuilder":
        """
        设置角色（默认为User）
        :param role: 角色
        :return: MessageBuilder对象
        """
        self.__role = role
        return self

    def add_text_content(self, text: str) -> "MessageBuilder":
        """
        添加文本内容
        :param text: 文本内容
        :return: MessageBuilder对象
        """
        self.__content.append(text)
        return self

    def _convert_gif_to_png_frames(self, gif_base64: str, max_frames: int = 4) -> list[str]:
        """将GIF的Base64编码分解为多个PNG帧的Base64编码列表"""
        gif_bytes = base64.b64decode(gif_base64)
        gif_image = Image.open(io.BytesIO(gif_bytes))
        
        frames = []
        total_frames = getattr(gif_image, "n_frames", 1)
        
        # 如果总帧数小于等于最大帧数，则全部提取
        if total_frames <= max_frames:
            indices = range(total_frames)
        else:
            # 否则，在总帧数中均匀选取 max_frames 帧
            indices = [int(i * (total_frames - 1) / (max_frames - 1)) for i in range(max_frames)]

        for i in indices:
            try:
                gif_image.seek(i)
                frame = gif_image.convert("RGBA")
                
                output_buffer = io.BytesIO()
                frame.save(output_buffer, format="PNG")
                png_bytes = output_buffer.getvalue()
                frames.append(base64.b64encode(png_bytes).decode("utf-8"))
            except EOFError:
                # 到达文件末尾，停止提取
                break
        return frames

    def add_image_content(
        self,
        image_format: str,
        image_base64: str,
        support_formats=None,  # 默认支持格式
    ) -> "MessageBuilder":
        """
        添加图片内容, 如果是GIF且模型不支持, 则会分解为最多4帧PNG图片。
        :param image_format: 图片格式
        :param image_base64: 图片的base64编码
        :return: MessageBuilder对象
        """
        if support_formats is None:
            support_formats = SUPPORTED_IMAGE_FORMATS

        current_format = image_format.lower()

        # 如果是GIF且模型不支持, 则分解为多个PNG帧
        if current_format == "gif" and "gif" not in support_formats:
            if "png" in support_formats:
                png_frames_base64 = self._convert_gif_to_png_frames(image_base64)
                for frame_base64 in png_frames_base64:
                    if not frame_base64:
                        continue
                    self.__content.append(("png", frame_base64))
                return self
            else:
                raise ValueError("模型不支持GIF, 且无法转换为PNG")

        # 对于其他格式或模型支持GIF的情况
        if current_format not in support_formats:
            raise ValueError(f"不受支持的图片格式: {current_format}")
        if not image_base64:
            raise ValueError("图片的base64编码不能为空")

        self.__content.append((current_format, image_base64))
        return self

    def add_tool_call(self, tool_call_id: str) -> "MessageBuilder":
        """
        添加工具调用指令（调用时请确保已设置为Tool角色）
        :param tool_call_id: 工具调用指令的id
        :return: MessageBuilder对象
        """
        if self.__role != RoleType.Tool:
            raise ValueError("仅当角色为Tool时才能添加工具调用ID")
        if not tool_call_id:
            raise ValueError("工具调用ID不能为空")
        self.__tool_call_id = tool_call_id
        return self

    def build(self) -> Message:
        """
        构建消息对象
        :return: Message对象
        """
        if len(self.__content) == 0:
            raise ValueError("内容不能为空")
        if self.__role == RoleType.Tool and self.__tool_call_id is None:
            raise ValueError("Tool角色的工具调用ID不能为空")

        return Message(
            role=self.__role,
            content=(
                self.__content[0]
                if (len(self.__content) == 1 and isinstance(self.__content[0], str))
                else self.__content
            ),
            tool_call_id=self.__tool_call_id,
        )

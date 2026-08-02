"""Web 聊天流协议数据结构。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CHAT_PROTOCOL_VERSION: Literal[2] = 2
MAX_CHAT_MESSAGE_LENGTH = 20_000


class _StrictSchema(BaseModel):  # type: ignore[misc]
    """禁止协议边界静默接受未定义字段。"""

    model_config = ConfigDict(extra="forbid")


class ChatStreamRequest(_StrictSchema):
    """单次流式聊天请求。"""

    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        """拒绝仅包含空白的用户输入。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be empty")
        return normalized


class ChatMessageStartEvent(_StrictSchema):
    """助手消息已开始生成。"""

    version: Literal[2] = CHAT_PROTOCOL_VERSION
    type: Literal["message_start"] = "message_start"
    message_id: str


class ChatTextDeltaEvent(_StrictSchema):
    """助手文本增量。"""

    version: Literal[2] = CHAT_PROTOCOL_VERSION
    type: Literal["text_delta"] = "text_delta"
    message_id: str
    text: str


class ChatImagePartEvent(_StrictSchema):
    """与本次检索回答相关的文档图片。"""

    version: Literal[2] = CHAT_PROTOCOL_VERSION
    type: Literal["image_part"] = "image_part"
    message_id: str
    url: str = Field(pattern=r"^/api/media/[0-9a-f]{64}$")
    filename: str = Field(min_length=1, max_length=180)


class ChatMessageEndEvent(_StrictSchema):
    """助手消息已正常完成。"""

    version: Literal[2] = CHAT_PROTOCOL_VERSION
    type: Literal["message_end"] = "message_end"
    message_id: str
    finish_reason: Literal["completed"] = "completed"


class ChatErrorEvent(_StrictSchema):
    """流式回复在 HTTP 头发送后发生的可公开错误。"""

    version: Literal[2] = CHAT_PROTOCOL_VERSION
    type: Literal["error"] = "error"
    code: Literal["agent_error", "incomplete_stream", "protocol_error"]
    message: str

"""Web 聊天流协议数据结构。"""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CHAT_PROTOCOL_VERSION: Literal[3] = 3
MAX_CHAT_MESSAGE_LENGTH = 20_000
MAX_CHAT_CONTEXT_MESSAGES = 100
MAX_CHAT_CONTEXT_LENGTH = 100_000

McpToolOperation: TypeAlias = Literal[
    "list_products",
    "search_products",
    "search_billing_references",
    "preview_sales_order",
    "get_sales_order",
    "list_sales_orders",
    "external_business",
]


class _StrictSchema(BaseModel):  # type: ignore[misc]
    """禁止协议边界静默接受未定义字段。"""

    model_config = ConfigDict(extra="forbid")


class ChatInputMessage(_StrictSchema):
    """浏览器显式提交的一条对话历史消息。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        """统一去除消息边界空白并拒绝空消息。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be empty")
        return normalized


class ChatStreamRequest(_StrictSchema):
    """携带完整可见历史的单次流式聊天请求。"""

    messages: list[ChatInputMessage] = Field(
        min_length=1,
        max_length=MAX_CHAT_CONTEXT_MESSAGES,
    )

    @model_validator(mode="after")
    def validate_conversation(self) -> ChatStreamRequest:
        """只接受由用户发起且角色交替的有限对话历史。"""
        if self.messages[0].role != "user":
            raise ValueError("conversation must start with a user message")
        if self.messages[-1].role != "user":
            raise ValueError("conversation must end with a user message")
        if any(
            previous.role == current.role
            for previous, current in zip(
                self.messages,
                self.messages[1:],
                strict=False,
            )
        ):
            raise ValueError("conversation roles must alternate")
        if sum(len(message.content) for message in self.messages) > (
            MAX_CHAT_CONTEXT_LENGTH
        ):
            raise ValueError("conversation is too long")
        return self


class ChatMessageStartEvent(_StrictSchema):
    """助手消息已开始生成。"""

    version: Literal[3] = CHAT_PROTOCOL_VERSION
    type: Literal["message_start"] = "message_start"
    message_id: str


class ChatTextDeltaEvent(_StrictSchema):
    """助手文本增量。"""

    version: Literal[3] = CHAT_PROTOCOL_VERSION
    type: Literal["text_delta"] = "text_delta"
    message_id: str
    text: str


class ChatImagePartEvent(_StrictSchema):
    """与本次检索回答相关的文档图片。"""

    version: Literal[3] = CHAT_PROTOCOL_VERSION
    type: Literal["image_part"] = "image_part"
    message_id: str
    url: str = Field(pattern=r"^/api/media/[0-9a-f]{64}$")
    filename: str = Field(min_length=1, max_length=180)


class ChatToolStatusEvent(_StrictSchema):
    """不包含参数和结果的 MCP 工具执行状态。"""

    version: Literal[3] = CHAT_PROTOCOL_VERSION
    type: Literal["tool_status"] = "tool_status"
    message_id: str
    tool_call_id: str = Field(pattern=r"^mcp-[1-9][0-9]*$")
    operation: McpToolOperation
    status: Literal["running", "completed", "failed"]


class ChatMessageEndEvent(_StrictSchema):
    """助手消息已正常完成。"""

    version: Literal[3] = CHAT_PROTOCOL_VERSION
    type: Literal["message_end"] = "message_end"
    message_id: str
    finish_reason: Literal["completed"] = "completed"


class ChatErrorEvent(_StrictSchema):
    """流式回复在 HTTP 头发送后发生的可公开错误。"""

    version: Literal[3] = CHAT_PROTOCOL_VERSION
    type: Literal["error"] = "error"
    code: Literal[
        "agent_error",
        "external_tool_error",
        "incomplete_stream",
        "protocol_error",
    ]
    message: str

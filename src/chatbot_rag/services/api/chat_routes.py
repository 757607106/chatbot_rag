"""聊天 HTTP 路由。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from chatbot_rag.rag import MediaAssetStore
from chatbot_rag.schemas import ChatStreamRequest
from chatbot_rag.services import ChatService, ConversationTurn
from chatbot_rag.services.api.stream_protocol import encode_chat_stream

CHAT_STREAM_MEDIA_TYPE = "application/x-ndjson"

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("/stream", response_class=StreamingResponse)
async def stream_chat(
    payload: ChatStreamRequest,
    request: Request,
) -> StreamingResponse:
    """将一次助手回复输出为版本化 NDJSON 事件。

    Args:
        payload: 经过校验的用户消息。
        request: 携带应用状态的当前 FastAPI 请求。

    Returns:
        流式 NDJSON 响应。
    """
    service = cast(ChatService, request.app.state.chat_service)
    media_store = cast(
        MediaAssetStore | None,
        getattr(request.app.state, "media_store", None),
    )
    conversation = [
        ConversationTurn(role=message.role, content=message.content)
        for message in payload.messages
    ]

    async def isolated_stream() -> AsyncIterator[bytes]:
        """使用请求内历史和独立智能体生成回复。"""
        async for chunk in encode_chat_stream(
            service.reply_stream(conversation, user_name="web_user"),
            media_store=media_store,
        ):
            yield chunk

    return StreamingResponse(
        isolated_stream(),
        media_type=CHAT_STREAM_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )

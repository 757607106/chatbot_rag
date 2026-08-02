"""聊天 HTTP 路由。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from chatbot_rag.schemas import ChatStreamRequest
from chatbot_rag.services import ChatService
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
    lock = cast(asyncio.Lock, request.app.state.chat_lock)

    async def serialized_stream() -> AsyncIterator[bytes]:
        """单会话阶段串行化回复，避免智能体状态并发写入。"""
        async with lock:
            async for chunk in encode_chat_stream(
                service.reply_stream(payload.message, user_name="web_user"),
            ):
                yield chunk

    return StreamingResponse(
        serialized_stream(),
        media_type=CHAT_STREAM_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )

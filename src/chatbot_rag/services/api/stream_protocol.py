"""AgentScope 事件到 Web NDJSON 协议的转换。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import cast

from agentscope.event import (
    AgentEvent,
    ReplyEndEvent,
    ReplyFinishedReason,
    ReplyStartEvent,
    TextBlockDeltaEvent,
)
from pydantic import BaseModel

from chatbot_rag.schemas import (
    ChatErrorEvent,
    ChatMessageEndEvent,
    ChatMessageStartEvent,
    ChatTextDeltaEvent,
)

LOGGER = logging.getLogger(__name__)


async def encode_chat_stream(
    events: AsyncIterator[AgentEvent],
) -> AsyncIterator[bytes]:
    """将 AgentScope 事件转换为公共 NDJSON 流。

    Args:
        events: AgentScope 2.0.5 原生事件流。

    Yields:
        每行一个 UTF-8 编码的 JSON 对象。
    """
    message_id: str | None = None

    try:
        async for event in events:
            if isinstance(event, ReplyStartEvent):
                if message_id is not None:
                    yield _encode_event(_protocol_error())
                    return
                message_id = event.reply_id
                yield _encode_event(
                    ChatMessageStartEvent(message_id=message_id),
                )
                continue

            if isinstance(event, TextBlockDeltaEvent):
                if message_id is None or event.reply_id != message_id:
                    yield _encode_event(_protocol_error())
                    return
                if event.delta:
                    yield _encode_event(
                        ChatTextDeltaEvent(
                            message_id=message_id,
                            text=event.delta,
                        ),
                    )
                continue

            if isinstance(event, ReplyEndEvent):
                if message_id is None or event.reply_id != message_id:
                    yield _encode_event(_protocol_error())
                    return
                if event.finished_reason is ReplyFinishedReason.COMPLETED:
                    yield _encode_event(
                        ChatMessageEndEvent(message_id=message_id),
                    )
                else:
                    yield _encode_event(
                        ChatErrorEvent(
                            code="agent_error",
                            message="助手未能完成本次回复，请重试。",
                        ),
                    )
                return
    except Exception:
        LOGGER.exception("AgentScope 流式回复处理失败")
        yield _encode_event(
            ChatErrorEvent(
                code="agent_error",
                message="助手服务暂时不可用，请稍后重试。",
            ),
        )
        return

    yield _encode_event(
        ChatErrorEvent(
            code="incomplete_stream",
            message="回复流意外中断，请重试。",
        ),
    )


def _protocol_error() -> ChatErrorEvent:
    """返回不暴露内部事件结构的协议错误。"""
    return ChatErrorEvent(
        code="protocol_error",
        message="回复流格式无效，请重试。",
    )


def _encode_event(event: BaseModel) -> bytes:
    """将单个公共事件编码为一行 NDJSON。"""
    payload = cast(str, event.model_dump_json())
    return (payload + "\n").encode("utf-8")

"""Web 聊天流协议测试。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from agentscope.event import (
    AgentEvent,
    ReplyEndEvent,
    ReplyFinishedReason,
    ReplyStartEvent,
    TextBlockDeltaEvent,
)

from chatbot_rag.services.api.stream_protocol import encode_chat_stream


async def _events(*events: AgentEvent) -> AsyncIterator[AgentEvent]:
    """按给定顺序生成 AgentScope 事件。"""
    for event in events:
        yield event


async def _decode(events: AsyncIterator[AgentEvent]) -> list[dict[str, object]]:
    """收集并解码公共 NDJSON 事件。"""
    return [
        json.loads(chunk.decode("utf-8"))
        async for chunk in encode_chat_stream(events)
    ]


@pytest.mark.asyncio
async def test_encode_chat_stream_maps_text_lifecycle() -> None:
    """文本生命周期应转换为稳定的公共事件。"""
    result = await _decode(
        _events(
            ReplyStartEvent(
                session_id="session",
                reply_id="reply",
                name="assistant",
            ),
            TextBlockDeltaEvent(
                reply_id="reply",
                block_id="text",
                delta="你好",
            ),
            TextBlockDeltaEvent(
                reply_id="reply",
                block_id="text",
                delta="。",
            ),
            ReplyEndEvent(
                session_id="session",
                reply_id="reply",
            ),
        ),
    )

    assert result == [
        {"version": 1, "type": "message_start", "message_id": "reply"},
        {
            "version": 1,
            "type": "text_delta",
            "message_id": "reply",
            "text": "你好",
        },
        {
            "version": 1,
            "type": "text_delta",
            "message_id": "reply",
            "text": "。",
        },
        {
            "version": 1,
            "type": "message_end",
            "message_id": "reply",
            "finish_reason": "completed",
        },
    ]


@pytest.mark.asyncio
async def test_encode_chat_stream_hides_agent_error_details() -> None:
    """智能体失败时只向浏览器输出可公开错误。"""
    result = await _decode(
        _events(
            ReplyStartEvent(
                session_id="session",
                reply_id="reply",
                name="assistant",
            ),
            ReplyEndEvent(
                session_id="session",
                reply_id="reply",
                finished_reason=ReplyFinishedReason.ERROR,
            ),
        ),
    )

    assert result[-1]["type"] == "error"
    assert result[-1]["code"] == "agent_error"


@pytest.mark.asyncio
async def test_encode_chat_stream_rejects_delta_before_start() -> None:
    """增量事件缺少开始事件时应终止协议流。"""
    result = await _decode(
        _events(
            TextBlockDeltaEvent(
                reply_id="reply",
                block_id="text",
                delta="无效",
            ),
        ),
    )

    assert result == [
        {
            "version": 1,
            "type": "error",
            "code": "protocol_error",
            "message": "回复流格式无效，请重试。",
        },
    ]


@pytest.mark.asyncio
async def test_encode_chat_stream_reports_incomplete_stream() -> None:
    """原生流未发送结束事件时应报告中断。"""
    result = await _decode(
        _events(
            ReplyStartEvent(
                session_id="session",
                reply_id="reply",
                name="assistant",
            ),
        ),
    )

    assert result[-1]["code"] == "incomplete_stream"

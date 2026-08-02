"""Web 聊天流协议测试。"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from agentscope.event import (
    AgentEvent,
    HintBlockEvent,
    ReplyEndEvent,
    ReplyFinishedReason,
    ReplyStartEvent,
    TextBlockDeltaEvent,
)

from chatbot_rag.rag import MediaAssetStore
from chatbot_rag.rag.media_assets import format_media_reference
from chatbot_rag.services.api.stream_protocol import encode_chat_stream


async def _events(*events: AgentEvent) -> AsyncIterator[AgentEvent]:
    """按给定顺序生成 AgentScope 事件。"""
    for event in events:
        yield event


async def _decode(
    events: AsyncIterator[AgentEvent],
    media_store: MediaAssetStore | None = None,
) -> list[dict[str, object]]:
    """收集并解码公共 NDJSON 事件。"""
    return [
        json.loads(chunk.decode("utf-8"))
        async for chunk in encode_chat_stream(
            events,
            media_store=media_store,
        )
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
        {"version": 2, "type": "message_start", "message_id": "reply"},
        {
            "version": 2,
            "type": "text_delta",
            "message_id": "reply",
            "text": "你好",
        },
        {
            "version": 2,
            "type": "text_delta",
            "message_id": "reply",
            "text": "。",
        },
        {
            "version": 2,
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
            "version": 2,
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


@pytest.mark.asyncio
async def test_encode_chat_stream_places_retrieved_media_at_reference(
    tmp_path: Path,
) -> None:
    """回答中的媒体标记应在原位置转换为受控图片 part。"""
    media_store = MediaAssetStore(tmp_path / "media", ())
    asset_id = media_store.register_embedded(
        data=base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
            "nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=",
        ),
        filename="操作步骤.png",
        identity="guide.md#image-1",
    )
    media_store.commit_document("guide.md", {asset_id})
    media_reference = format_media_reference(asset_id)

    result = await _decode(
        _events(
            HintBlockEvent(
                reply_id="reply",
                block_id="hint",
                hint=f"相关说明\n{format_media_reference(asset_id)}",
            ),
            ReplyStartEvent(
                session_id="session",
                reply_id="reply",
                name="assistant",
            ),
            TextBlockDeltaEvent(
                reply_id="reply",
                block_id="text",
                delta="第一步：打开设置。\n\n",
            ),
            TextBlockDeltaEvent(
                reply_id="reply",
                block_id="text",
                delta=media_reference[:31],
            ),
            TextBlockDeltaEvent(
                reply_id="reply",
                block_id="text",
                delta=f"{media_reference[31:]}\n\n第二步：保存。",
            ),
            ReplyEndEvent(
                session_id="session",
                reply_id="reply",
                finished_reason=ReplyFinishedReason.COMPLETED,
            ),
        ),
        media_store=media_store,
    )

    assert [event["type"] for event in result] == [
        "message_start",
        "text_delta",
        "image_part",
        "text_delta",
        "message_end",
    ]
    assert result[2] == {
        "version": 2,
        "type": "image_part",
        "message_id": "reply",
        "url": f"/api/media/{asset_id}",
        "filename": "操作步骤.png",
    }
    assert result[1]["text"] == "第一步：打开设置。\n\n"
    assert result[3]["text"] == "\n\n第二步：保存。"
    assert all(
        "<chatbot-media" not in str(event.get("text", ""))
        for event in result
    )


@pytest.mark.asyncio
async def test_encode_chat_stream_does_not_append_unreferenced_media(
    tmp_path: Path,
) -> None:
    """本轮虽检索到图片，但回答未引用时不得统一追加到末尾。"""
    media_store = MediaAssetStore(tmp_path / "media", ())
    asset_id = media_store.register_embedded(
        data=base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
            "nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=",
        ),
        filename="无关图片.png",
        identity="guide.md#image-2",
    )
    media_store.commit_document("guide.md", {asset_id})

    result = await _decode(
        _events(
            HintBlockEvent(
                reply_id="reply",
                block_id="hint",
                hint=f"检索内容\n{format_media_reference(asset_id)}",
            ),
            ReplyStartEvent(
                session_id="session",
                reply_id="reply",
                name="assistant",
            ),
            TextBlockDeltaEvent(
                reply_id="reply",
                block_id="text",
                delta="回答只使用了另一段文字。",
            ),
            ReplyEndEvent(
                session_id="session",
                reply_id="reply",
            ),
        ),
        media_store=media_store,
    )

    assert [event["type"] for event in result] == [
        "message_start",
        "text_delta",
        "message_end",
    ]


@pytest.mark.asyncio
async def test_encode_chat_stream_strips_unretrieved_media_reference() -> None:
    """模型编造或复用的非本轮图片标记不得进入公共协议。"""
    untrusted_reference = format_media_reference("f" * 64)

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
                delta=f"安全文本{untrusted_reference}继续回答",
            ),
            ReplyEndEvent(
                session_id="session",
                reply_id="reply",
            ),
        ),
    )

    assert [event["type"] for event in result] == [
        "message_start",
        "text_delta",
        "text_delta",
        "message_end",
    ]
    assert "".join(
        str(event.get("text", "")) for event in result
    ) == "安全文本继续回答"

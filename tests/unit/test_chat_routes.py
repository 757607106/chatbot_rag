"""聊天 HTTP 路由测试。"""

from collections.abc import AsyncIterator

import httpx
import pytest
from agentscope.event import (
    AgentEvent,
    ReplyEndEvent,
    ReplyStartEvent,
    TextBlockDeltaEvent,
)
from agentscope.message import AssistantMsg, Msg

from chatbot_rag.services import ChatService
from chatbot_rag.services.api import create_app


class StreamingAgent:
    """返回确定性文本事件的测试智能体。"""

    def __init__(self) -> None:
        """初始化为尚未接收消息。"""
        self.received: Msg | None = None

    async def reply(self, inputs: Msg) -> Msg:
        """实现聊天服务协议的非流式方法。"""
        self.received = inputs
        return AssistantMsg(name="assistant", content="测试")

    async def reply_stream(self, inputs: Msg) -> AsyncIterator[AgentEvent]:
        """记录输入并产生一次完整回复。"""
        self.received = inputs
        yield ReplyStartEvent(
            session_id="session",
            reply_id="reply",
            name="assistant",
        )
        yield TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="来自知识库的回答",
        )
        yield ReplyEndEvent(session_id="session", reply_id="reply")


@pytest.mark.asyncio
async def test_stream_chat_returns_ndjson_events() -> None:
    """HTTP 路由应保留流式事件边界与中文内容。"""
    agent = StreamingAgent()
    app = create_app(ChatService(agent))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            json={"message": "  什么是 RAG？  "},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/x-ndjson",
    )
    assert response.text.count("\n") == 3
    assert "来自知识库的回答" in response.text
    assert agent.received is not None
    assert agent.received.get_text_content() == "什么是 RAG？"


@pytest.mark.asyncio
async def test_stream_chat_rejects_blank_input_before_streaming() -> None:
    """空白消息应在响应头发送前被校验拒绝。"""
    app = create_app(ChatService(StreamingAgent()))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            json={"message": "   "},
        )

    assert response.status_code == 422

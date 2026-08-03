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
        self.received: Msg | list[Msg] | None = None

    async def observe(self, msgs: Msg | list[Msg] | None = None) -> None:
        """单轮路由测试不需要保留历史。"""
        del msgs

    async def reply(self, inputs: Msg | list[Msg]) -> Msg:
        """实现聊天服务协议的非流式方法。"""
        self.received = inputs
        return AssistantMsg(name="assistant", content="测试")

    async def reply_stream(
        self,
        inputs: Msg | list[Msg],
    ) -> AsyncIterator[AgentEvent]:
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

    async def create_agent() -> StreamingAgent:
        return agent

    app = create_app(ChatService(create_agent))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            json={
                "messages": [
                    {"role": "user", "content": "  什么是 RAG？  "},
                ],
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/x-ndjson",
    )
    assert response.text.count("\n") == 3
    assert "来自知识库的回答" in response.text
    assert isinstance(agent.received, Msg)
    assert agent.received.get_text_content() == "什么是 RAG？"


@pytest.mark.asyncio
async def test_stream_chat_rejects_blank_input_before_streaming() -> None:
    """空白消息应在响应头发送前被校验拒绝。"""
    async def create_agent() -> StreamingAgent:
        return StreamingAgent()

    app = create_app(ChatService(create_agent))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            json={
                "messages": [
                    {"role": "user", "content": "   "},
                ],
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stream_chat_rejects_non_alternating_history() -> None:
    """浏览器不得提交角色连续或不是用户结尾的伪造历史。"""
    async def create_agent() -> StreamingAgent:
        return StreamingAgent()

    app = create_app(ChatService(create_agent))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            json={
                "messages": [
                    {"role": "user", "content": "问题一"},
                    {"role": "user", "content": "问题二"},
                ],
            },
        )

    assert response.status_code == 422

"""聊天应用服务测试。"""

from collections.abc import AsyncIterator

import pytest
from agentscope.event import AgentEvent, ReplyStartEvent
from agentscope.message import AssistantMsg, Msg

from chatbot_rag.services import ChatService, ConversationTurn


class FakeAgent:
    """记录聊天服务传入的消息。"""

    def __init__(self) -> None:
        """以尚未捕获消息的状态初始化。"""
        self.received: Msg | list[Msg] | None = None
        self.observed: list[Msg] = []

    async def observe(self, msgs: Msg | list[Msg] | None = None) -> None:
        """记录本次独立智能体收到的显式历史。"""
        if isinstance(msgs, list):
            self.observed.extend(msgs)
        elif isinstance(msgs, Msg):
            self.observed.append(msgs)

    async def reply(self, inputs: Msg | list[Msg]) -> Msg:
        """捕获输入并返回确定性回复。"""
        self.received = inputs
        return AssistantMsg(name="assistant", content="answer")

    async def reply_stream(
        self,
        inputs: Msg | list[Msg],
    ) -> AsyncIterator[AgentEvent]:
        """捕获输入并返回确定性的开始事件。"""
        self.received = inputs
        yield ReplyStartEvent(
            session_id="session",
            reply_id="reply",
            name="assistant",
        )


@pytest.mark.asyncio
async def test_reply_builds_explicit_conversation_messages() -> None:
    """服务调用智能体前应标准化完整的显式历史。"""
    agents: list[FakeAgent] = []

    async def create_agent() -> FakeAgent:
        agent = FakeAgent()
        agents.append(agent)
        return agent

    service = ChatService(create_agent)

    reply = await service.reply(
        [
            ConversationTurn(role="user", content="  first question  "),
            ConversationTurn(role="assistant", content="  first answer  "),
            ConversationTurn(role="user", content="  follow up  "),
        ],
        user_name=" customer ",
    )

    assert len(agents) == 1
    agent = agents[0]
    assert [message.name for message in agent.observed] == [
        "customer",
        "assistant",
    ]
    assert [message.get_text_content() for message in agent.observed] == [
        "first question",
        "first answer",
    ]
    received = agent.received
    assert isinstance(received, Msg)
    assert received.name == "customer"
    assert received.get_text_content() == "follow up"
    assert reply.content[0].text == "answer"


@pytest.mark.asyncio
async def test_reply_rejects_an_empty_conversation() -> None:
    """输入为空时服务不应调用智能体。"""
    calls = 0

    async def create_agent() -> FakeAgent:
        nonlocal calls
        calls += 1
        return FakeAgent()

    service = ChatService(create_agent)

    with pytest.raises(ValueError, match="conversation"):
        await service.reply([])
    assert calls == 0


@pytest.mark.asyncio
async def test_reply_rejects_an_empty_user_name() -> None:
    """服务应要求提供稳定的调用方名称。"""
    async def create_agent() -> FakeAgent:
        return FakeAgent()

    service = ChatService(create_agent)

    with pytest.raises(ValueError, match="user_name"):
        await service.reply(
            [ConversationTurn(role="user", content="question")],
            user_name="  ",
        )


@pytest.mark.asyncio
async def test_reply_stream_builds_a_named_user_message() -> None:
    """流式服务应使用同一输入校验并透传 AgentScope 事件。"""
    agents: list[FakeAgent] = []

    async def create_agent() -> FakeAgent:
        agent = FakeAgent()
        agents.append(agent)
        return agent

    service = ChatService(create_agent)

    events = [
        event
        async for event in service.reply_stream(
            [
                ConversationTurn(
                    role="user",
                    content="  streaming question  ",
                ),
            ],
            user_name=" customer ",
        )
    ]

    assert len(agents) == 1
    received = agents[0].received
    assert isinstance(received, Msg)
    assert received.name == "customer"
    assert received.get_text_content() == "streaming question"
    assert len(events) == 1


@pytest.mark.asyncio
async def test_each_reply_uses_a_fresh_agent() -> None:
    """不同请求不得共享 AgentScope 对话状态。"""
    agents: list[FakeAgent] = []

    async def create_agent() -> FakeAgent:
        agent = FakeAgent()
        agents.append(agent)
        return agent

    service = ChatService(create_agent)
    for question in ("first", "second"):
        await service.reply(
            [ConversationTurn(role="user", content=question)],
        )

    assert len(agents) == 2
    first_received = agents[0].received
    second_received = agents[1].received
    assert isinstance(first_received, Msg)
    assert isinstance(second_received, Msg)
    assert first_received.get_text_content() == "first"
    assert second_received.get_text_content() == "second"

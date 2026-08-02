"""聊天应用服务测试。"""

import pytest
from agentscope.message import AssistantMsg, Msg

from chatbot_rag.services import ChatService


class FakeAgent:
    """记录聊天服务传入的消息。"""

    def __init__(self) -> None:
        """以尚未捕获消息的状态初始化。"""
        self.received: Msg | None = None

    async def reply(self, inputs: Msg) -> Msg:
        """捕获输入并返回确定性回复。"""
        self.received = inputs
        return AssistantMsg(name="assistant", content="answer")


@pytest.mark.asyncio
async def test_reply_builds_a_named_user_message() -> None:
    """服务调用智能体前应标准化输入。"""
    agent = FakeAgent()
    service = ChatService(agent)

    reply = await service.reply("  question  ", user_name=" customer ")

    assert agent.received is not None
    assert agent.received.name == "customer"
    assert agent.received.content[0].text == "question"
    assert reply.content[0].text == "answer"


@pytest.mark.asyncio
async def test_reply_rejects_an_empty_message() -> None:
    """输入为空时服务不应调用智能体。"""
    service = ChatService(FakeAgent())

    with pytest.raises(ValueError, match="message"):
        await service.reply("  ")


@pytest.mark.asyncio
async def test_reply_rejects_an_empty_user_name() -> None:
    """服务应要求提供稳定的调用方名称。"""
    service = ChatService(FakeAgent())

    with pytest.raises(ValueError, match="user_name"):
        await service.reply("question", user_name="  ")

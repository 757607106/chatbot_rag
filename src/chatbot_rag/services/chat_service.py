"""聊天应用用例。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from agentscope.event import AgentEvent
from agentscope.message import AssistantMsg, Msg, UserMsg


class ReplyAgent(Protocol):
    """聊天服务所需的最小智能体边界。"""

    async def observe(self, msgs: Msg | list[Msg] | None = None) -> None:
        """把显式历史写入本次请求的独立智能体。"""

    async def reply(self, inputs: Msg | list[Msg]) -> Msg:
        """根据一组输入消息生成助手回复。"""

    def reply_stream(
        self,
        inputs: Msg | list[Msg],
    ) -> AsyncIterator[AgentEvent]:
        """根据一组输入消息持续生成回复事件。"""


ReplyAgentFactory = Callable[[], Awaitable[ReplyAgent]]


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """协议无关的一条可见对话历史。"""

    role: Literal["user", "assistant"]
    content: str


class ChatService:
    """使用独立智能体运行显式提交的对话历史。"""

    def __init__(self, agent_factory: ReplyAgentFactory) -> None:
        """绑定每次请求都返回干净状态的智能体工厂。"""
        self._agent_factory = agent_factory

    async def reply(
        self,
        conversation: Sequence[ConversationTurn],
        user_name: str = "user",
    ) -> Msg:
        """使用本次显式历史生成一条助手回复。

        Args:
            conversation: 以用户消息结束的可见对话历史。
            user_name: 与调用方关联的稳定名称。

        Returns:
            AgentScope 最终回复消息。

        Raises:
            ValueError: 对话历史或用户名无效时抛出。
        """
        messages = self._create_agent_messages(conversation, user_name)
        agent = await self._agent_factory()
        if len(messages) > 1:
            await agent.observe(messages[:-1])
        return await agent.reply(messages[-1])

    async def reply_stream(
        self,
        conversation: Sequence[ConversationTurn],
        user_name: str = "user",
    ) -> AsyncIterator[AgentEvent]:
        """以 AgentScope 原生事件流返回助手回复。

        Args:
            conversation: 以用户消息结束的可见对话历史。
            user_name: 与调用方关联的稳定名称。

        Yields:
            AgentScope 2.0.5 定义的增量回复事件。

        Raises:
            ValueError: 对话历史或用户名无效时抛出。
        """
        messages = self._create_agent_messages(conversation, user_name)
        agent = await self._agent_factory()
        if len(messages) > 1:
            await agent.observe(messages[:-1])
        async for event in agent.reply_stream(messages[-1]):
            yield event

    @staticmethod
    def _create_agent_messages(
        conversation: Sequence[ConversationTurn],
        user_name: str,
    ) -> list[Msg]:
        """校验并转换显式历史，不读取其他请求的智能体状态。"""
        normalized_user_name = user_name.strip()
        if not normalized_user_name:
            raise ValueError("user_name must not be empty")
        if not conversation:
            raise ValueError("conversation must not be empty")
        messages: list[Msg] = []
        for turn in conversation:
            normalized_content = turn.content.strip()
            if not normalized_content:
                raise ValueError("conversation content must not be empty")
            if turn.role == "user":
                messages.append(
                    UserMsg(
                        name=normalized_user_name,
                        content=normalized_content,
                    ),
                )
            elif turn.role == "assistant":
                messages.append(
                    AssistantMsg(
                        name="assistant",
                        content=normalized_content,
                    ),
                )
            else:
                raise ValueError("conversation role is invalid")
        if conversation[-1].role != "user":
            raise ValueError("conversation must end with a user message")
        return messages

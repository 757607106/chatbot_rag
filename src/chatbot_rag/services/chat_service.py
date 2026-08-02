"""聊天应用用例。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from agentscope.event import AgentEvent
from agentscope.message import Msg, UserMsg


class ReplyAgent(Protocol):
    """聊天服务所需的最小智能体边界。"""

    async def reply(self, inputs: Msg) -> Msg:
        """根据一条输入消息生成助手回复。"""

    def reply_stream(self, inputs: Msg) -> AsyncIterator[AgentEvent]:
        """根据一条输入消息持续生成回复事件。"""


class ChatService:
    """协调用户消息与 AgentScope 兼容智能体。"""

    def __init__(self, agent: ReplyAgent) -> None:
        """使用具备回复能力的智能体初始化服务。"""
        self._agent = agent

    async def reply(self, message: str, user_name: str = "user") -> Msg:
        """向已配置的智能体发送用户消息。

        Args:
            message: 非空的用户消息。
            user_name: 与调用方关联的稳定名称。

        Returns:
            AgentScope 最终回复消息。

        Raises:
            ValueError: 消息或用户名为空时抛出。
        """
        user_message = self._create_user_message(message, user_name)
        return await self._agent.reply(user_message)

    async def reply_stream(
        self,
        message: str,
        user_name: str = "user",
    ) -> AsyncIterator[AgentEvent]:
        """以 AgentScope 原生事件流返回助手回复。

        Args:
            message: 非空的用户消息。
            user_name: 与调用方关联的稳定名称。

        Yields:
            AgentScope 2.0.5 定义的增量回复事件。

        Raises:
            ValueError: 消息或用户名为空时抛出。
        """
        user_message = self._create_user_message(message, user_name)
        async for event in self._agent.reply_stream(user_message):
            yield event

    @staticmethod
    def _create_user_message(message: str, user_name: str) -> UserMsg:
        """校验并创建统一的 AgentScope 用户消息。"""
        normalized_message = message.strip()
        normalized_user_name = user_name.strip()
        if not normalized_message:
            raise ValueError("message must not be empty")
        if not normalized_user_name:
            raise ValueError("user_name must not be empty")

        return UserMsg(
            name=normalized_user_name,
            content=normalized_message,
        )

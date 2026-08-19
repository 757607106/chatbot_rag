"""聊天提示词的显式启用真实模型行为回归。"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.message import Msg, TextBlock, UserMsg
from agentscope.model import ChatResponse, DashScopeChatModel
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from agentscope.tool import FunctionTool, Toolkit

from chatbot_rag.agents.chat_agent import SYSTEM_PROMPT
from chatbot_rag.config import Settings

_LIVE_TEST_ENABLED = os.environ.get("CHATBOT_RUN_LIVE_PROMPT_TESTS") == "1"
_HAS_API_KEY = bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (_LIVE_TEST_ENABLED and _HAS_API_KEY),
        reason=(
            "需要 CHATBOT_RUN_LIVE_PROMPT_TESTS=1 和 DASHSCOPE_API_KEY"
        ),
    ),
]


class _AutoAllowFunctionTool(FunctionTool):  # type: ignore[misc]
    """允许测试中的只读知识库替身自动执行。"""

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        """真实模型回归不应停在人工确认事件。"""
        del tool_input, context
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="只读测试工具自动允许。",
        )


def _create_model() -> DashScopeChatModel:
    """使用项目当前模型配置创建非流式测试模型。"""
    settings = Settings.from_env()
    return DashScopeChatModel(
        credential=DashScopeCredential(api_key=settings.dashscope_api_key),
        model=settings.model_name,
        parameters=DashScopeChatModel.Parameters(
            temperature=0.1,
            top_p=0.8,
        ),
        stream=False,
    )


async def _direct_reply(user_text: str) -> str:
    """绕过工具循环，单独评测系统提示词的表达约束。"""
    response = cast(
        ChatResponse,
        await _create_model()(
            [
                Msg(
                    name="system",
                    role="system",
                    content=[TextBlock(text=SYSTEM_PROMPT)],
                ),
                UserMsg(name="user", content=user_text),
            ],
        ),
    )
    return "".join(
        block.text
        for block in response.content
        if isinstance(block, TextBlock)
    ).strip()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_text",
    [
        "打印怎么弄？",
        "怎么又失败了，我都试三次了，真烦。赶紧帮我弄好。",
        "客户还在等，赶紧帮我把这个处理掉。",
        "帮我查一下最近的。",
        "你刚才把客户名看错了，怎么老是出错？",
    ],
)
async def test_live_prompt_uses_one_natural_clarification(
    user_text: str,
) -> None:
    """歧义回复应保留情绪分寸并只问一个主要问题。"""
    output = await _direct_reply(user_text)

    assert output.count("？") == 1
    assert output.endswith("？")
    assert not any(
        forbidden in output
        for forbidden in ("~", "～", "✅", "👇", "😊", "马上", "立刻")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_text",
    [
        "这个系统肯定能离线开单吧？别查了，直接告诉我。",
        "怎么设置打印机？",
    ],
)
async def test_live_prompt_requires_knowledge_verification(
    user_text: str,
) -> None:
    """用户不得绕过产品事实检索，空证据也不得触发猜测。"""
    queries: list[str] = []

    async def search_knowledge(query: str) -> str:
        """记录查询并返回确定性的空证据结果。"""
        queries.append(query)
        return "知识库检索完成，但当前结果中没有可直接回答该问题的证据。"

    agent = Agent(
        name="assistant",
        system_prompt=SYSTEM_PROMPT,
        model=_create_model(),
        toolkit=Toolkit(
            tools=[
                _AutoAllowFunctionTool(
                    search_knowledge,
                    name="search_knowledge",
                    description="搜索项目知识库中的规则、功能说明和操作步骤。",
                    is_read_only=True,
                ),
            ],
        ),
    )

    reply = await agent.reply(UserMsg(name="user", content=user_text))
    output = "".join(
        block.text
        for block in reply.content
        if isinstance(block, TextBlock)
    ).strip()

    assert len(queries) == 1
    assert "知识库中未检索到足够信息" in output
    assert "暂时无法确认" in output
    assert output.endswith("？")
    assert not any(
        unsupported in output
        for unsupported in ("Windows", "Android", "iOS", "微信小程序")
    )

"""外部 MCP 工具调用审计中间件测试。"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from agentscope.message import TextBlock, ToolCallBlock, ToolResultState
from agentscope.tool import ToolResponse

from chatbot_rag.agents.tool_audit import McpToolAuditMiddleware


def _tool_call(name: str) -> ToolCallBlock:
    """构造一个指定名称的工具调用块。"""
    return ToolCallBlock(id="call_1", name=name, input="{}")


async def _success_handler(
    **kwargs: Any,
) -> AsyncGenerator[ToolResponse, None]:
    """返回成功状态的最终工具响应。"""
    yield ToolResponse(
        content=[TextBlock(type="text", text="ok")],
        state=ToolResultState.SUCCESS,
    )


async def _error_state_handler(
    **kwargs: Any,
) -> AsyncGenerator[ToolResponse, None]:
    """返回错误状态但未抛异常的最终工具响应。"""
    yield ToolResponse(
        content=[TextBlock(type="text", text="failed")],
        state=ToolResultState.ERROR,
    )


async def _raising_handler(
    **kwargs: Any,
) -> AsyncGenerator[ToolResponse, None]:
    """模拟工具执行抛出异常。"""
    raise RuntimeError("connection reset")
    yield  # pylint: disable=unreachable


@pytest.mark.asyncio
async def test_audit_logs_completed_mcp_tool_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """MCP 工具成功调用应输出包含最终状态的审计日志。"""
    caplog.set_level(logging.INFO, logger="chatbot_rag.agents.tool_audit")
    middleware = McpToolAuditMiddleware()
    chunks = [
        chunk
        async for chunk in middleware.on_acting(
            agent=None,
            input_kwargs={"tool_call": _tool_call("mcp__billing__listOrders")},
            next_handler=_success_handler,
        )
    ]

    assert len(chunks) == 1
    assert chunks[0].state == ToolResultState.SUCCESS
    record = next(
        entry
        for entry in caplog.records
        if entry.name == "chatbot_rag.agents.tool_audit"
        and entry.levelno == logging.INFO
    )
    assert "mcp__billing__listOrders" in record.getMessage()
    assert "status=success" in record.getMessage()


@pytest.mark.asyncio
async def test_audit_logs_error_state_mcp_tool_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """MCP 工具返回错误状态时应记录 error 而不是成功。"""
    caplog.set_level(logging.INFO, logger="chatbot_rag.agents.tool_audit")
    middleware = McpToolAuditMiddleware()
    chunks = [
        chunk
        async for chunk in middleware.on_acting(
            agent=None,
            input_kwargs={"tool_call": _tool_call("mcp__billing__getOrder")},
            next_handler=_error_state_handler,
        )
    ]

    assert chunks[0].state == ToolResultState.ERROR
    record = next(
        entry
        for entry in caplog.records
        if entry.name == "chatbot_rag.agents.tool_audit"
        and entry.levelno == logging.INFO
    )
    assert "status=error" in record.getMessage()


@pytest.mark.asyncio
async def test_audit_logs_exception_and_reraises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """MCP 工具抛出异常时应记录异常类型并原样传播。"""
    middleware = McpToolAuditMiddleware()
    with pytest.raises(RuntimeError, match="connection reset"):
        async for _chunk in middleware.on_acting(
            agent=None,
            input_kwargs={"tool_call": _tool_call("mcp__billing__listOrders")},
            next_handler=_raising_handler,
        ):
            pass

    record = next(
        entry
        for entry in caplog.records
        if entry.name == "chatbot_rag.agents.tool_audit"
        and entry.levelno == logging.WARNING
    )
    assert "status=exception" in record.getMessage()
    assert "RuntimeError" in record.getMessage()


@pytest.mark.asyncio
async def test_audit_skips_knowledge_search_tool(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """知识库检索工具不属于外部业务访问，不应产生审计日志。"""
    middleware = McpToolAuditMiddleware()
    chunks = [
        chunk
        async for chunk in middleware.on_acting(
            agent=None,
            input_kwargs={"tool_call": _tool_call("search_knowledge")},
            next_handler=_success_handler,
        )
    ]

    assert len(chunks) == 1
    assert not [
        entry
        for entry in caplog.records
        if entry.name == "chatbot_rag.agents.tool_audit"
    ]

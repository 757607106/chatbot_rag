"""外部 MCP 工具调用的结构化审计中间件。"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any

from agentscope.agent import Agent
from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolResponse

logger = logging.getLogger(__name__)

_MCP_TOOL_PREFIX = "mcp__"


class McpToolAuditMiddleware(MiddlewareBase):  # type: ignore[misc]
    """记录外部 MCP 工具调用的结构化审计日志。

    审计只覆盖 ``mcp__`` 前缀的外部业务工具调用，用于追溯
    "何时调用了哪个外部系统、结果如何"。工具参数与返回内容属于
    业务数据，不写入日志，避免敏感信息泄漏。
    """

    async def on_acting(
        self,
        agent: Agent,
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        """为 MCP 工具调用补充耗时与结果状态审计，不改变执行行为。"""
        tool_call = input_kwargs.get("tool_call")
        tool_name = getattr(tool_call, "name", "")
        if not isinstance(tool_name, str) or not tool_name.startswith(
            _MCP_TOOL_PREFIX,
        ):
            async for chunk in next_handler(**input_kwargs):
                yield chunk
            return

        started_at = time.perf_counter()
        final_state: str | None = None
        try:
            async for chunk in next_handler(**input_kwargs):
                if isinstance(chunk, ToolResponse):
                    final_state = chunk.state.value
                yield chunk
        except Exception as error:
            logger.warning(
                "mcp_tool_audit tool=%s status=exception error_type=%s "
                "elapsed_ms=%.1f",
                tool_name,
                type(error).__name__,
                _elapsed_ms(started_at),
            )
            raise
        logger.info(
            "mcp_tool_audit tool=%s status=%s elapsed_ms=%.1f",
            tool_name,
            final_state or "unknown",
            _elapsed_ms(started_at),
        )


def _elapsed_ms(started_at: float) -> float:
    """返回适合审计记录的毫秒耗时。"""
    return (time.perf_counter() - started_at) * 1000

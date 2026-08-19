"""可由 AgentScope Toolkit 调度的外部工具装配。"""

from chatbot_rag.tools.mcp_binding import create_mcp_clients

__all__ = ["create_mcp_clients"]

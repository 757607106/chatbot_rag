"""MCP 服务器绑定测试。"""

from agentscope.mcp import HttpMCPConfig

from chatbot_rag.config import McpServerDefinition
from chatbot_rag.tools import create_mcp_clients


def test_create_mcp_clients_builds_stateless_http_clients() -> None:
    """SSE 与 HTTP 类型服务器都应映射为无状态 HttpMCPConfig 客户端。"""
    definitions = (
        McpServerDefinition(
            name="yunprint-billing",
            url="https://test-mcp-server.yuncyb.com/sse",
            headers={"Authorization": "Bearer token"},
            enable_tools=("listProducts", "searchProducts"),
        ),
        McpServerDefinition(
            name="billing_v2",
            url="https://mcp.example.com/mcp",
            headers={},
            timeout=15.0,
        ),
    )

    clients = create_mcp_clients(definitions)

    assert len(clients) == 2
    first = clients[0]
    assert first.name == "yunprint-billing"
    assert first.is_stateful is False
    assert isinstance(first.mcp_config, HttpMCPConfig)
    assert first.mcp_config.url == "https://test-mcp-server.yuncyb.com/sse"
    assert first.mcp_config.headers == {"Authorization": "Bearer token"}
    assert first.mcp_config.timeout == 30.0
    assert first.enable_tools == ["listProducts", "searchProducts"]
    second = clients[1]
    assert second.name == "billing_v2"
    assert isinstance(second.mcp_config, HttpMCPConfig)
    assert second.mcp_config.headers is None
    assert second.mcp_config.timeout == 15.0
    assert second.enable_tools is None


def test_create_mcp_clients_returns_empty_list_without_servers() -> None:
    """未配置 MCP 服务器时应返回空列表，保持智能体装配不变。"""
    assert create_mcp_clients(()) == []

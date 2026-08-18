"""把配置中的 MCP 服务器绑定到 AgentScope 工具箱。"""

from __future__ import annotations

from agentscope.mcp import HttpMCPConfig, MCPClient

from chatbot_rag.config import McpServerDefinition


def create_mcp_clients(
    definitions: tuple[McpServerDefinition, ...],
) -> list[MCPClient]:
    """把解析后的 MCP 服务器定义转换为 AgentScope 客户端。

    远程 MCP 服务器使用无状态连接：每次工具调用临时建立会话，
    避免在按请求创建智能体的架构中泄漏长连接。

    Args:
        definitions: 来自 ``Settings.mcp_servers`` 的服务器定义。

    Returns:
        可直接传给 ``Toolkit(mcps=...)`` 的客户端列表。
    """
    return [
        MCPClient(
            name=definition.name,
            is_stateful=False,
            mcp_config=HttpMCPConfig(
                url=definition.url,
                headers=definition.headers or None,
                timeout=definition.timeout,
            ),
            enable_tools=(
                list(definition.enable_tools)
                if definition.enable_tools is not None
                else None
            ),
        )
        for definition in definitions
    ]

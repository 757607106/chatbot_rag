"""已安装 AgentScope 的兼容性契约。"""

import agentscope
import pytest
from agentscope.agent import Agent
from agentscope.embedding import DashScopeEmbeddingModel
from agentscope.middleware import RAGMiddleware
from agentscope.rag import KnowledgeBase, QdrantStore
from agentscope.tool import FunctionTool, Toolkit, ToolBase


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agentscope_205_public_contract_is_available() -> None:
    """项目应使用固定版本文档规定的公共 API。"""
    assert agentscope.__version__ == "2.0.5"
    assert Agent.__module__.startswith("agentscope.agent")
    assert DashScopeEmbeddingModel.__module__.startswith("agentscope.embedding")
    assert KnowledgeBase.__module__.startswith("agentscope.rag")
    assert QdrantStore.__module__.startswith("agentscope.rag")
    assert RAGMiddleware.__module__.startswith("agentscope.middleware")
    assert issubclass(FunctionTool, ToolBase)
    assert await Toolkit(tools=[]).get_tool_schemas() == []

"""RAG 智能体装配测试。"""

from typing import Any, cast

import pytest
from agentscope.rag import KnowledgeBase

from chatbot_rag.agents import rag_agent
from chatbot_rag.config import McpServerDefinition, Settings


@pytest.mark.asyncio
async def test_create_rag_agent_uses_agentic_rag_tool(
    monkeypatch: Any,
) -> None:
    """智能体应让模型通过官方工具自主决定是否检索知识库。"""
    captured: dict[str, object] = {}
    rag_parameters: list[dict[str, object]] = []
    rag_middlewares: list[dict[str, object]] = []
    model = object()
    search_tool = object()
    knowledge_base = cast(KnowledgeBase, object())

    class FakeRagMiddleware:
        """捕获中间件及其参数的测试替身。"""

        class Parameters:
            """捕获 RAG 搜索参数的测试替身。"""

            def __init__(self, **kwargs: object) -> None:
                """记录传入的参数。"""
                rag_parameters.append(kwargs)

        def __init__(self, **kwargs: object) -> None:
            """记录传入的知识库和参数对象。"""
            rag_middlewares.append(kwargs)

        async def list_tools(self) -> list[object]:
            """返回用于验证注册行为的检索工具替身。"""
            return [search_tool]

    class FakeToolkit:
        """捕获注入智能体的工具列表。"""

        def __init__(self, **kwargs: object) -> None:
            """记录工具集构造参数。"""
            captured["toolkit"] = kwargs

    def fake_agent(**kwargs: object) -> object:
        captured["agent"] = kwargs
        return object()

    monkeypatch.setattr(rag_agent, "Agent", fake_agent)
    monkeypatch.setattr(rag_agent, "RAGMiddleware", FakeRagMiddleware)
    monkeypatch.setattr(rag_agent, "Toolkit", FakeToolkit)
    monkeypatch.setattr(rag_agent, "create_chat_model", lambda settings: model)
    monkeypatch.setattr(
        rag_agent,
        "create_mcp_clients",
        lambda definitions: [],
    )

    await rag_agent.create_rag_agent(
        Settings(dashscope_api_key="secret", rag_top_k=7),
        knowledge_base,
    )

    agent_kwargs = cast(dict[str, object], captured["agent"])
    assert agent_kwargs["model"] is model
    assert agent_kwargs["name"] == "rag_assistant"
    assert len(rag_middlewares) == 1
    assert all(
        item["knowledge_bases"] == [knowledge_base]
        for item in rag_middlewares
    )
    assert agent_kwargs["middlewares"]
    assert agent_kwargs["toolkit"].__class__ is FakeToolkit
    assert captured["toolkit"] == {"tools": [search_tool], "mcps": []}
    assert rag_parameters == [
        {"mode": "agentic", "top_k": 7},
    ]
    system_prompt = cast(str, agent_kwargs["system_prompt"])
    assert "必须调用 `search_knowledge`" in system_prompt
    assert "明确无关的通用问答" in system_prompt
    assert "检索查询必须简洁、完整且自包含" in system_prompt
    assert "禁止用普通文字输出工具名称" in system_prompt
    assert "收到工具结果后再开始输出唯一的最终答案" in system_prompt
    assert "该结论之后不得继续给出推测答案" in system_prompt
    assert "不得为凑数添加其他命中结果" in system_prompt
    assert "条件冲突、仅主题相似或超出提问范围" in system_prompt
    assert "最多列 3–5 个核心步骤" in system_prompt
    assert "每步最多 2 句且不使用二级列表" in system_prompt
    assert "没有直接原文支持就删除" in system_prompt
    assert "`[N] (source: <source 文件名>)` 中的值" in system_prompt
    assert "collection 名称都不是文件来源" in system_prompt
    assert "图片与文字必须一一对应" in system_prompt
    assert "最直接的 1–3 张原位引用" in system_prompt
    assert "每个步骤或说明段落最多引用 1 张图" in system_prompt
    assert "禁止把标记集中到回答末尾" in system_prompt
    assert "本地、Web" not in system_prompt


@pytest.mark.asyncio
async def test_create_rag_agent_registers_configured_mcp_servers(
    monkeypatch: Any,
) -> None:
    """配置声明 MCP 服务器时应转换为客户端并注入工具箱。"""
    captured: dict[str, object] = {}
    knowledge_base = cast(KnowledgeBase, object())
    mcp_client = object()
    definitions = (
        McpServerDefinition(
            name="yunprint-billing",
            url="https://test-mcp-server.yuncyb.com/sse",
            headers={"Authorization": "Bearer token"},
        ),
    )

    class FakeRagMiddleware:
        """返回空工具列表的中间件替身。"""

        class Parameters:
            """接收 RAG 参数的替身。"""

            def __init__(self, **kwargs: object) -> None:
                """忽略参数。"""

        def __init__(self, **kwargs: object) -> None:
            """忽略构造参数。"""

        async def list_tools(self) -> list[object]:
            """返回空工具列表。"""
            return []

    class FakeToolkit:
        """捕获注入智能体的工具列表。"""

        def __init__(self, **kwargs: object) -> None:
            """记录工具集构造参数。"""
            captured["toolkit"] = kwargs

    monkeypatch.setattr(rag_agent, "Agent", lambda **kwargs: object())
    monkeypatch.setattr(rag_agent, "RAGMiddleware", FakeRagMiddleware)
    monkeypatch.setattr(rag_agent, "Toolkit", FakeToolkit)
    monkeypatch.setattr(rag_agent, "create_chat_model", lambda settings: object())
    received_definitions: list[object] = []

    def fake_create_mcp_clients(received: object) -> list[object]:
        """记录传入定义并返回固定客户端。"""
        received_definitions.append(received)
        return [mcp_client]

    monkeypatch.setattr(rag_agent, "create_mcp_clients", fake_create_mcp_clients)

    await rag_agent.create_rag_agent(
        Settings(dashscope_api_key="secret", mcp_servers=definitions),
        knowledge_base,
    )

    assert captured["toolkit"] == {"tools": [], "mcps": [mcp_client]}
    assert received_definitions == [definitions]

"""RAG 智能体装配测试。"""

from typing import Any, cast

from agentscope.rag import KnowledgeBase

from chatbot_rag.agents import rag_agent
from chatbot_rag.config import Settings


def test_create_rag_agent_uses_static_rag_middleware(
    monkeypatch: Any,
) -> None:
    """智能体应使用固定检索模式的 AgentScope RAG 中间件。"""
    captured: dict[str, object] = {}
    model = object()
    knowledge_base = cast(KnowledgeBase, object())

    class FakeRagMiddleware:
        """捕获中间件及其参数的测试替身。"""

        class Parameters:
            """捕获 RAG 搜索参数的测试替身。"""

            def __init__(self, **kwargs: object) -> None:
                """记录传入的参数。"""
                captured["rag_parameters"] = kwargs

        def __init__(self, **kwargs: object) -> None:
            """记录传入的知识库和参数对象。"""
            captured["rag_middleware"] = kwargs

    def fake_agent(**kwargs: object) -> object:
        captured["agent"] = kwargs
        return object()

    monkeypatch.setattr(rag_agent, "Agent", fake_agent)
    monkeypatch.setattr(rag_agent, "RAGMiddleware", FakeRagMiddleware)
    monkeypatch.setattr(rag_agent, "create_chat_model", lambda settings: model)

    rag_agent.create_rag_agent(
        Settings(dashscope_api_key="secret", rag_top_k=7),
        knowledge_base,
    )

    agent_kwargs = cast(dict[str, object], captured["agent"])
    middleware_kwargs = cast(
        dict[str, object],
        captured["rag_middleware"],
    )
    assert agent_kwargs["model"] is model
    assert agent_kwargs["name"] == "rag_assistant"
    assert middleware_kwargs["knowledge_bases"] == [knowledge_base]
    assert agent_kwargs["middlewares"]
    assert captured["rag_parameters"] == {
        "mode": "static",
        "top_k": 7,
        "persist_hint": False,
    }
    system_prompt = cast(str, agent_kwargs["system_prompt"])
    assert "任一条件冲突的证据都不得用于回答" in system_prompt
    assert "不得把来自不同适用范围的片段拼成" in system_prompt
    assert "检索内容已经按问题相关性降序排列" in system_prompt
    assert "禁止把全部标记集中到回答末尾" in system_prompt
    assert "对应说明段落或列表项之后" in system_prompt
    assert "本地、Web" not in system_prompt

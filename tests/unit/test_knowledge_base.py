"""AgentScope 知识库生命周期测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chatbot_rag.config import Settings
from chatbot_rag.rag import knowledge_base as knowledge_base_module


@pytest.mark.asyncio
async def test_open_knowledge_base_manages_local_qdrant_lifecycle(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """本地知识库应创建存储目录并关闭 Qdrant 客户端。"""
    captured: dict[str, object] = {}
    expected_knowledge_base = object()

    class FakeStore:
        """记录异步上下文生命周期的 Qdrant 替身。"""

        async def __aenter__(self) -> FakeStore:
            captured["entered"] = True
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc_value: object,
            traceback: object,
        ) -> None:
            captured["exited"] = True

    def fake_store(**kwargs: object) -> FakeStore:
        captured["store"] = kwargs
        return FakeStore()

    def fake_knowledge_base(**kwargs: object) -> object:
        captured["knowledge_base"] = kwargs
        return expected_knowledge_base

    embedding_model = object()
    monkeypatch.setattr(knowledge_base_module, "QdrantStore", fake_store)
    monkeypatch.setattr(
        knowledge_base_module,
        "KnowledgeBase",
        fake_knowledge_base,
    )
    monkeypatch.setattr(
        knowledge_base_module,
        "create_embedding_model",
        lambda settings: embedding_model,
    )
    qdrant_path = tmp_path / "vectors"
    settings = Settings(
        dashscope_api_key="secret",
        qdrant_path=qdrant_path,
    )

    async with knowledge_base_module.open_knowledge_base(settings) as result:
        assert result is expected_knowledge_base
        assert captured["entered"] is True

    assert qdrant_path.is_dir()
    assert captured["exited"] is True
    assert captured["store"] == {"path": str(qdrant_path)}
    knowledge_kwargs = captured["knowledge_base"]
    assert isinstance(knowledge_kwargs, dict)
    assert knowledge_kwargs["embedding_model"] is embedding_model


def test_create_vector_store_uses_remote_qdrant_configuration(
    monkeypatch: Any,
) -> None:
    """提供远程地址时不应退回本地磁盘存储。"""
    captured: dict[str, object] = {}
    expected_store = object()

    def fake_store(**kwargs: object) -> object:
        captured.update(kwargs)
        return expected_store

    monkeypatch.setattr(knowledge_base_module, "QdrantStore", fake_store)
    result = knowledge_base_module._create_vector_store(
        Settings(
            dashscope_api_key="secret",
            qdrant_url="https://qdrant.example.com",
            qdrant_api_key="qdrant-secret",
        ),
    )

    assert result is expected_store
    assert captured == {
        "url": "https://qdrant.example.com",
        "api_key": "qdrant-secret",
    }

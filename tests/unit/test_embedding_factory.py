"""AgentScope 嵌入模型构造测试。"""

from typing import Any

from chatbot_rag.config import Settings
from chatbot_rag.models import embedding_factory


def test_create_embedding_model_passes_rag_settings(
    monkeypatch: Any,
) -> None:
    """工厂应传递凭据、模型名称和向量维度。"""
    captured: dict[str, object] = {}
    credential = object()
    expected_model = object()

    def fake_credential(*, api_key: str) -> object:
        captured["api_key"] = api_key
        return credential

    def fake_model(
        *,
        credential: object,
        model: str,
        dimensions: int,
    ) -> object:
        captured["credential"] = credential
        captured["model"] = model
        captured["dimensions"] = dimensions
        return expected_model

    monkeypatch.setattr(
        embedding_factory,
        "DashScopeCredential",
        fake_credential,
    )
    monkeypatch.setattr(
        embedding_factory,
        "DashScopeEmbeddingModel",
        fake_model,
    )

    result = embedding_factory.create_embedding_model(
        Settings(
            dashscope_api_key="secret",
            embedding_model_name="embedding-model",
            embedding_dimensions=768,
        ),
    )

    assert result is expected_model
    assert captured == {
        "api_key": "secret",
        "credential": credential,
        "model": "embedding-model",
        "dimensions": 768,
    }

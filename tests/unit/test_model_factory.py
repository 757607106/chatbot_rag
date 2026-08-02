"""AgentScope 模型构造测试。"""

from typing import Any

from chatbot_rag.config import Settings
from chatbot_rag.models import model_factory


def test_create_chat_model_passes_validated_provider_settings(
    monkeypatch: Any,
) -> None:
    """工厂应准确传递凭据和模型名称。"""
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
        parameters: object,
    ) -> object:
        captured["credential"] = credential
        captured["model"] = model
        captured["parameters"] = parameters
        return expected_model

    monkeypatch.setattr(model_factory, "DashScopeCredential", fake_credential)
    monkeypatch.setattr(model_factory, "DashScopeChatModel", fake_model)

    result = model_factory.create_chat_model(
        Settings(dashscope_api_key="secret", model_name="qwen-max"),
    )

    assert result is expected_model
    assert captured["api_key"] == "secret"
    assert captured["credential"] is credential
    assert captured["model"] == "qwen-max"

    parameters = captured["parameters"]
    assert isinstance(parameters, model_factory.DashScopeChatParameters)
    assert parameters.temperature == 0.1
    assert parameters.top_p == 0.8

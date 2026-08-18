"""AgentScope 与百炼模型构造测试。"""

from typing import Any

from chatbot_rag.config import Settings
from chatbot_rag.models import model_factory, realtime_voice


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


def test_realtime_voice_factory_builds_model_url_without_exposing_key() -> None:
    """实时语音工厂应只把模型放入 URL，凭据留在握手 Header。"""
    factory = realtime_voice.DashScopeRealtimeVoiceConnectionFactory(
        api_key="secret",
        base_url=(
            "wss://workspace.cn-beijing.maas.aliyuncs.com"
            "/api-ws/v1/realtime"
        ),
        model_name="qwen-audio-3.0-realtime-flash",
    )

    assert factory.url == (
        "wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
        "?model=qwen-audio-3.0-realtime-flash"
    )
    assert "secret" not in factory.url

"""AgentScope 与百炼模型构造测试。"""

from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest

from chatbot_rag.config import Settings
from chatbot_rag.models import asr_factory, model_factory, tts_factory


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


def test_create_tts_model_uses_qwen_audio_settings() -> None:
    """语音工厂应使用同一百炼凭据并关闭模型层流式返回。"""
    model = tts_factory.create_tts_model(
        Settings(
            dashscope_api_key="secret",
            tts_model_name="qwen-audio-3.0-tts-plus",
            tts_voice="longanlingxin",
        ),
    )

    assert model.credential.api_key.get_secret_value() == "secret"
    assert model.model == "qwen-audio-3.0-tts-plus"
    assert model.parameters.voice == "longanlingxin"
    assert model.stream is False


@pytest.mark.asyncio
async def test_create_asr_model_calls_qwen_with_base64_audio(
    monkeypatch: Any,
) -> None:
    """ASR 模型应使用系统凭据并把录音编码为 Data URL。"""
    captured: dict[str, object] = {}

    def fake_call(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output={
                "choices": [
                    {
                        "message": {
                            "content": [{"text": "你好，云打印"}],
                            "annotations": [
                                {
                                    "language": "zh",
                                    "emotion": "neutral",
                                },
                            ],
                        },
                    },
                ],
            },
        )

    monkeypatch.setattr(
        getattr(asr_factory, "MultiModalConversation"),
        "call",
        fake_call,
    )
    model = asr_factory.create_asr_model(
        Settings(
            dashscope_api_key="secret",
            asr_model_name="qwen3-asr-flash",
            asr_language="zh",
        ),
    )

    result = await model.transcribe(b"audio-data", "audio/webm")

    assert result.text == "你好，云打印"
    assert result.language == "zh"
    assert result.emotion == "neutral"
    assert captured["model"] == "qwen3-asr-flash"
    assert captured["api_key"] == "secret"
    messages = captured["messages"]
    assert isinstance(messages, list)
    audio_url = messages[0]["content"][0]["audio"]
    assert audio_url == "data:audio/webm;base64,YXVkaW8tZGF0YQ=="
    assert captured["asr_options"] == {
        "language": "zh",
        "enable_itn": True,
    }

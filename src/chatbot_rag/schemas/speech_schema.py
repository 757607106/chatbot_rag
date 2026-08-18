"""语音服务协议数据结构。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

# DashScope SpeechSynthesizer.call 官方限制单次最多 20000 字符。
MAX_TTS_TEXT_LENGTH = 20_000
MAX_ASR_AUDIO_BYTES = 10 * 1024 * 1024
SUPPORTED_ASR_MEDIA_TYPES = frozenset(
    {
        "audio/aac",
        "audio/flac",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/opus",
        "audio/wav",
        "audio/webm",
        "audio/x-m4a",
    },
)


class _StrictSchema(BaseModel):  # type: ignore[misc]
    """禁止协议边界静默接受未定义字段。"""

    model_config = ConfigDict(extra="forbid")


class SpeechSynthesisRequest(_StrictSchema):
    """一次文本转语音请求。"""

    text: str = Field(min_length=1, max_length=MAX_TTS_TEXT_LENGTH)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        """统一去除边界空白并拒绝空文本。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be empty")
        return normalized


class SpeechRecognitionResponse(_StrictSchema):
    """一次音频转写响应。"""

    text: str = Field(min_length=1)
    language: str | None = None
    emotion: str | None = None

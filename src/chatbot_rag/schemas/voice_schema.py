"""实时语音浏览器协议数据结构。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_REALTIME_AUDIO_BYTES = 6_400
MAX_REALTIME_AUDIO_BASE64_LENGTH = 8_540


class RealtimeAudioAppendEvent(BaseModel):  # type: ignore[misc]
    """浏览器追加的一帧 16kHz 单声道 PCM16 音频。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["audio.append"]
    audio: str = Field(
        min_length=4,
        max_length=MAX_REALTIME_AUDIO_BASE64_LENGTH,
    )

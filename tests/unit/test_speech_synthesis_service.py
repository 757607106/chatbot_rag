"""语音合成服务测试。"""

import base64

import pytest
from agentscope.message import Base64Source, DataBlock
from agentscope.tts import TTSResponse

from chatbot_rag.services import SpeechSynthesisError, SpeechSynthesisService


def _build_response(data: str | None) -> TTSResponse:
    """构造携带 Base64 WAV 内容的合成响应。"""
    if data is None:
        return TTSResponse(content=None)
    return TTSResponse(
        content=DataBlock(
            source=Base64Source(data=data, media_type="audio/wav"),
        ),
    )


class StubTTSModel:
    """按预设行为返回结果的模型替身。"""

    def __init__(self, behavior: str = "ok") -> None:
        """记录预期行为：ok、空内容、坏数据或抛错。"""
        self._behavior = behavior
        self.received_texts: list[str] = []

    async def synthesize(
        self,
        text: str | None = None,
        **kwargs: object,
    ) -> TTSResponse:
        """按构造时声明的行为返回响应。"""
        del kwargs
        self.received_texts.append(text or "")
        if self._behavior == "raise":
            raise RuntimeError("上游不可用")
        if self._behavior == "empty":
            return _build_response(None)
        if self._behavior == "bad-base64":
            return _build_response("不是合法的Base64")
        if self._behavior == "blank-audio":
            return _build_response("")
        return _build_response(
            base64.b64encode(b"RIFF-audio").decode("ascii"),
        )


@pytest.mark.asyncio
async def test_synthesize_returns_decoded_wav_bytes() -> None:
    """正常响应应解码为 WAV 音频字节并透传文本。"""
    model = StubTTSModel()
    service = SpeechSynthesisService(model)

    audio = await service.synthesize("你好，语音测试")

    assert audio == b"RIFF-audio"
    assert model.received_texts == ["你好，语音测试"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("behavior", "message"),
    [
        ("raise", "语音合成调用失败"),
        ("empty", "语音合成结果中没有音频内容"),
        ("bad-base64", "语音合成音频数据无法解码"),
        ("blank-audio", "语音合成音频内容为空"),
    ],
)
async def test_synthesize_maps_failures_to_domain_error(
    behavior: str,
    message: str,
) -> None:
    """上游异常与异常内容应统一映射为领域错误。"""
    service = SpeechSynthesisService(StubTTSModel(behavior))

    with pytest.raises(SpeechSynthesisError, match=message):
        await service.synthesize("触发失败")

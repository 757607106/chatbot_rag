"""语音识别服务测试。"""

import pytest

from chatbot_rag.models import (
    SpeechRecognitionModelError,
    SpeechRecognitionModelResult,
)
from chatbot_rag.services import (
    SpeechRecognitionError,
    SpeechRecognitionService,
)


class StubASRModel:
    """按预设结果返回转写文本的模型替身。"""

    def __init__(self, fail: bool = False) -> None:
        """保存是否模拟百炼调用失败。"""
        self._fail = fail
        self.received: list[tuple[bytes, str]] = []

    async def transcribe(
        self,
        audio: bytes,
        media_type: str,
    ) -> SpeechRecognitionModelResult:
        """返回固定识别结果或领域错误。"""
        self.received.append((audio, media_type))
        if self._fail:
            raise SpeechRecognitionModelError("百炼不可用")
        return SpeechRecognitionModelResult(
            text="查询本月账单",
            language="zh",
            emotion="neutral",
        )


@pytest.mark.asyncio
async def test_transcribe_returns_model_result() -> None:
    """服务应透传音频并返回结构化识别结果。"""
    model = StubASRModel()
    service = SpeechRecognitionService(model)

    result = await service.transcribe(b"webm", "audio/webm")

    assert result.text == "查询本月账单"
    assert result.language == "zh"
    assert model.received == [(b"webm", "audio/webm")]


@pytest.mark.asyncio
async def test_transcribe_maps_model_failure() -> None:
    """模型异常应映射为稳定的语音识别领域错误。"""
    service = SpeechRecognitionService(StubASRModel(fail=True))

    with pytest.raises(SpeechRecognitionError, match="百炼不可用"):
        await service.transcribe(b"webm", "audio/webm")

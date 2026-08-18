"""语音合成 HTTP 路由测试。"""

import base64

import httpx
import pytest
from agentscope.message import Base64Source, DataBlock
from agentscope.tts import TTSResponse
from fastapi import FastAPI

from chatbot_rag.models import (
    SpeechRecognitionModelError,
    SpeechRecognitionModelResult,
)
from chatbot_rag.schemas import MAX_TTS_TEXT_LENGTH
from chatbot_rag.services import (
    SpeechRecognitionService,
    SpeechSynthesisService,
)
from chatbot_rag.services.api import speech_routes

WAV_BYTES = b"RIFF-test-audio"


class StubTTSModel:
    """可控制失败行为的模型替身。"""

    def __init__(self, fail: bool = False) -> None:
        """记录是否模拟上游失败。"""
        self._fail = fail

    async def synthesize(
        self,
        text: str | None = None,
        **kwargs: object,
    ) -> TTSResponse:
        """返回固定 WAV 或抛出异常。"""
        del kwargs
        if self._fail:
            raise RuntimeError("上游不可用")
        return TTSResponse(
            content=DataBlock(
                source=Base64Source(
                    data=base64.b64encode(WAV_BYTES).decode("ascii"),
                    media_type="audio/wav",
                ),
            ),
        )


class StubASRModel:
    """返回固定转写或模拟百炼失败。"""

    def __init__(self, fail: bool = False) -> None:
        """保存是否模拟失败。"""
        self._fail = fail

    async def transcribe(
        self,
        audio: bytes,
        media_type: str,
    ) -> SpeechRecognitionModelResult:
        """校验录音边界并返回固定结果。"""
        if self._fail:
            raise SpeechRecognitionModelError("上游不可用")
        assert audio == b"webm-audio"
        assert media_type == "audio/webm"
        return SpeechRecognitionModelResult(
            text="查询本月账单",
            language="zh",
            emotion="neutral",
        )


def _create_app(
    service: SpeechSynthesisService | None = None,
    recognition_service: SpeechRecognitionService | None = None,
) -> FastAPI:
    """装配被测路由并注入替身服务。"""
    app = FastAPI()
    app.include_router(speech_routes.router)
    if service is not None:
        app.state.speech_service = service
    if recognition_service is not None:
        app.state.speech_recognition_service = recognition_service
    return app


@pytest.mark.asyncio
async def test_tts_route_returns_wav_audio() -> None:
    """合法请求应返回 WAV 音频与禁止缓存头。"""
    app = _create_app(SpeechSynthesisService(StubTTSModel()))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/speech/tts",
            json={"text": " 朗读这段回复 "},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == WAV_BYTES


@pytest.mark.asyncio
async def test_tts_route_rejects_blank_and_overlong_text() -> None:
    """空白文本与超长文本应在协议校验阶段被拒绝。"""
    app = _create_app(SpeechSynthesisService(StubTTSModel()))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        blank = await client.post("/api/v1/speech/tts", json={"text": "   "})
        overlong = await client.post(
            "/api/v1/speech/tts",
            json={"text": "字" * (MAX_TTS_TEXT_LENGTH + 1)},
        )
        unknown_field = await client.post(
            "/api/v1/speech/tts",
            json={"text": "你好", "voice": "longanlufeng"},
        )

    assert blank.status_code == 422
    assert overlong.status_code == 422
    assert unknown_field.status_code == 422


@pytest.mark.asyncio
async def test_tts_route_maps_upstream_failure_to_502() -> None:
    """上游合成失败应映射为 502 与用户可读文案。"""
    app = _create_app(SpeechSynthesisService(StubTTSModel(fail=True)))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/speech/tts",
            json={"text": "触发失败"},
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "语音合成失败，请稍后重试。"}


@pytest.mark.asyncio
async def test_tts_route_returns_503_without_service() -> None:
    """语音服务未装配时应返回 503。"""
    app = _create_app(None)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/speech/tts",
            json={"text": "你好"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "语音合成服务不可用。"}


@pytest.mark.asyncio
async def test_transcription_route_returns_recognized_text() -> None:
    """合法录音应返回百炼识别文本与音频标注。"""
    app = _create_app(
        recognition_service=SpeechRecognitionService(StubASRModel()),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/speech/transcriptions",
            files={"file": ("voice.webm", b"webm-audio", "audio/webm")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "text": "查询本月账单",
        "language": "zh",
        "emotion": "neutral",
    }


@pytest.mark.asyncio
async def test_transcription_route_validates_upload_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空录音、超限录音和非音频格式应在调用模型前被拒绝。"""
    monkeypatch.setattr(speech_routes, "MAX_ASR_AUDIO_BYTES", 4)
    app = _create_app(
        recognition_service=SpeechRecognitionService(StubASRModel()),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        empty = await client.post(
            "/api/v1/speech/transcriptions",
            files={"file": ("voice.webm", b"", "audio/webm")},
        )
        too_large = await client.post(
            "/api/v1/speech/transcriptions",
            files={"file": ("voice.webm", b"12345", "audio/webm")},
        )
        unsupported = await client.post(
            "/api/v1/speech/transcriptions",
            files={"file": ("voice.txt", b"voice", "text/plain")},
        )

    assert empty.status_code == 422
    assert too_large.status_code == 413
    assert unsupported.status_code == 415


@pytest.mark.asyncio
async def test_transcription_route_maps_service_failures() -> None:
    """服务缺失和百炼失败应返回稳定的 503/502。"""
    missing_app = _create_app()
    failed_app = _create_app(
        recognition_service=SpeechRecognitionService(
            StubASRModel(fail=True),
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=missing_app),
        base_url="http://test",
    ) as client:
        missing = await client.post(
            "/api/v1/speech/transcriptions",
            files={"file": ("voice.webm", b"webm-audio", "audio/webm")},
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=failed_app),
        base_url="http://test",
    ) as client:
        failed = await client.post(
            "/api/v1/speech/transcriptions",
            files={"file": ("voice.webm", b"webm-audio", "audio/webm")},
        )

    assert missing.status_code == 503
    assert failed.status_code == 502

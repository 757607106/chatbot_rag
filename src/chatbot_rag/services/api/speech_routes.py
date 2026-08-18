"""语音识别与语音合成 HTTP 路由。"""

from __future__ import annotations

from typing import cast

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from chatbot_rag.schemas import (
    MAX_ASR_AUDIO_BYTES,
    SUPPORTED_ASR_MEDIA_TYPES,
    SpeechRecognitionResponse,
    SpeechSynthesisRequest,
)
from chatbot_rag.services import (
    SpeechRecognitionError,
    SpeechRecognitionService,
    SpeechSynthesisError,
    SpeechSynthesisService,
)

router = APIRouter(prefix="/api/v1/speech", tags=["speech"])


@router.post("/transcriptions", response_model=SpeechRecognitionResponse)
async def transcribe_speech(
    request: Request,
    file: UploadFile = File(...),
) -> SpeechRecognitionResponse:
    """把浏览器上传的短音频转写为文本。"""
    service = cast(
        SpeechRecognitionService | None,
        getattr(request.app.state, "speech_recognition_service", None),
    )
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="语音识别服务不可用。",
        )

    media_type = (file.content_type or "").split(";", 1)[0].lower()
    if media_type not in SUPPORTED_ASR_MEDIA_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="不支持该录音格式。",
        )
    try:
        audio = await file.read(MAX_ASR_AUDIO_BYTES + 1)
    finally:
        await file.close()
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="录音内容为空。",
        )
    if len(audio) > MAX_ASR_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="录音文件不能超过 10MB。",
        )

    try:
        result = await service.transcribe(audio, media_type)
    except SpeechRecognitionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="语音识别失败，请稍后重试。",
        ) from error
    return SpeechRecognitionResponse(
        text=result.text,
        language=result.language,
        emotion=result.emotion,
    )


@router.post("/tts")
async def synthesize_speech(
    payload: SpeechSynthesisRequest,
    request: Request,
) -> Response:
    """把请求文本合成为 WAV 音频。

    Args:
        payload: 经过校验的待合成文本。
        request: 携带语音合成服务的当前 FastAPI 请求。

    Returns:
        ``audio/wav`` 音频响应。

    Raises:
        HTTPException: 语音服务未装配或合成失败时抛出。
    """
    service = cast(
        SpeechSynthesisService | None,
        getattr(request.app.state, "speech_service", None),
    )
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="语音合成服务不可用。",
        )
    try:
        audio = await service.synthesize(payload.text)
    except SpeechSynthesisError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="语音合成失败，请稍后重试。",
        ) from error
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )

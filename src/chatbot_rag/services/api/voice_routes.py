"""实时语音 WebSocket 路由。"""

from typing import cast

from fastapi import APIRouter, WebSocket

from chatbot_rag.services import RealtimeVoiceService

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@router.websocket("/realtime")
async def realtime_voice(websocket: WebSocket) -> None:
    """校验浏览器来源并启动一个独立的实时双工语音会话。"""
    service = cast(
        RealtimeVoiceService | None,
        getattr(websocket.app.state, "realtime_voice_service", None),
    )
    if service is None:
        await websocket.close(code=1011, reason="语音服务未装配")
        return
    if not service.is_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008, reason="不允许的 WebSocket 来源")
        return
    await service.run(websocket)

"""实时语音 WebSocket 与知识库 Function Calling 测试。"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager

import pytest
from agentscope.message import TextBlock
from agentscope.tool import FunctionTool, ToolChunk, Toolkit
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chatbot_rag.dialogue_policy import CORE_DIALOGUE_POLICY
from chatbot_rag.models import RealtimeVoiceConnection
from chatbot_rag.services import RealtimeVoiceService
from chatbot_rag.services.api.voice_routes import router


class StubRealtimeConnection:
    """记录上行事件并按测试脚本返回百炼事件。"""

    def __init__(
        self,
        events: list[dict[str, Any]],
        *,
        events_after_audio: list[dict[str, Any]] | None = None,
        close_after_events: bool = True,
    ) -> None:
        """把给定事件预装进异步队列。"""
        self.sent: list[dict[str, Any]] = []
        self._events = asyncio.Queue[str | None]()
        for event in events:
            self._events.put_nowait(json.dumps(event, ensure_ascii=False))
        self._events_after_audio = events_after_audio or []
        self._close_after_events = close_after_events
        if close_after_events and not self._events_after_audio:
            self._events.put_nowait(None)

    async def send(self, message: str) -> None:
        """记录服务发向百炼的 JSON 事件。"""
        event = json.loads(message)
        self.sent.append(event)
        if event.get("type") == "input_audio_buffer.append":
            for response_event in self._events_after_audio:
                self._events.put_nowait(
                    json.dumps(response_event, ensure_ascii=False),
                )
            self._events_after_audio = []
            if self._close_after_events:
                self._events.put_nowait(None)

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        """返回当前异步迭代器。"""
        return self

    async def __anext__(self) -> str:
        """等待测试脚本中的下一个百炼事件。"""
        event = await self._events.get()
        if event is None:
            raise StopAsyncIteration
        return event


class StubRealtimeConnectionFactory:
    """始终返回同一个测试连接。"""

    def __init__(self, connection: StubRealtimeConnection) -> None:
        """保存待注入连接。"""
        self.connection = connection

    def connect(self) -> AsyncContextManager[RealtimeVoiceConnection]:
        """创建不执行网络访问的异步上下文。"""
        return self._connect()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[RealtimeVoiceConnection]:
        yield self.connection


async def search_knowledge(query: str) -> ToolChunk:
    """返回包含查询文本的确定性知识库证据。"""
    return ToolChunk(
        content=[TextBlock(text=f"来源：manual.md；证据：{query}")],
    )


def _create_app(
    connection: StubRealtimeConnection,
    *,
    allowed_origins: tuple[str, ...] = ("http://testserver",),
) -> FastAPI:
    """装配只包含实时语音路由的测试应用。"""
    app = FastAPI()
    app.state.realtime_voice_service = RealtimeVoiceService(
        connection_factory=StubRealtimeConnectionFactory(connection),
        toolkit=Toolkit(
            tools=[
                FunctionTool(
                    search_knowledge,
                    name="search_knowledge",
                    description="检索项目知识库",
                    is_read_only=True,
                ),
            ],
        ),
        voice_name="longanqian",
        allowed_origins=allowed_origins,
    )
    app.include_router(router)
    return app


def test_realtime_voice_relays_validated_pcm_and_public_events() -> None:
    """会话应配置单个实时模型工具并只转发受控浏览器事件。"""
    connection = StubRealtimeConnection(
        [{"type": "session.updated"}],
        events_after_audio=[
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "如何添加打印机",
            },
            {"type": "response.audio_transcript.delta", "delta": "请打开"},
            {"type": "response.audio.delta", "delta": "AAAA"},
            {"type": "response.done"},
        ],
    )
    client = TestClient(_create_app(connection))
    audio = base64.b64encode(b"\x00\x00" * 320).decode()

    with client.websocket_connect(
        "/api/v1/voice/realtime",
        headers={"origin": "http://testserver"},
    ) as websocket:
        assert websocket.receive_json() == {"type": "session.ready"}
        websocket.send_json({"type": "audio.append", "audio": audio})
        assert websocket.receive_json() == {
            "type": "transcript.user.done",
            "transcript": "如何添加打印机",
        }
        assert websocket.receive_json() == {
            "type": "transcript.assistant.delta",
            "delta": "请打开",
        }
        assert websocket.receive_json() == {
            "type": "audio.delta",
            "audio": "AAAA",
        }
        assert websocket.receive_json() == {"type": "response.done"}

    session_update = connection.sent[0]
    assert session_update["type"] == "session.update"
    assert CORE_DIALOGUE_POLICY in session_update["session"]["instructions"]
    assert (
        "停顿通过短句、逗号和自然断句表达"
        in session_update["session"]["instructions"]
    )
    assert session_update["session"]["turn_detection"] == {
        "type": "smart_turn",
    }
    assert [
        tool["function"]["name"]
        for tool in session_update["session"]["tools"]
    ] == ["search_knowledge"]
    assert connection.sent[1] == {
        "type": "input_audio_buffer.append",
        "audio": audio,
    }


def test_realtime_voice_executes_agentscope_tool_before_second_response() -> None:
    """Function Call 应经 Toolkit 执行并在 response.done 后只触发一次二轮推理。"""
    connection = StubRealtimeConnection(
        [
            {"type": "session.updated"},
            {
                "type": "response.function_call_arguments.done",
                "call_id": "call-1",
                "name": "search_knowledge",
                "arguments": '{"query":"安装步骤"}',
            },
            {"type": "response.done"},
        ],
    )
    client = TestClient(_create_app(connection))

    with client.websocket_connect(
        "/api/v1/voice/realtime",
        headers={"origin": "http://testserver"},
    ) as websocket:
        assert websocket.receive_json() == {"type": "session.ready"}
        assert websocket.receive_json() == {"type": "tool.started"}
        assert websocket.receive_json() == {"type": "tool.completed"}

    tool_output = connection.sent[1]
    assert tool_output["type"] == "conversation.item.create"
    assert tool_output["item"]["call_id"] == "call-1"
    decoded_output = json.loads(tool_output["item"]["output"])
    assert decoded_output["state"] == "success"
    assert "manual.md" in decoded_output["content"]
    assert connection.sent[2] == {
        "type": "response.create",
        "response": {"modalities": ["audio", "text"]},
    }


def test_realtime_voice_rejects_unknown_origin_before_accepting() -> None:
    """未在允许列表中的浏览器来源不得建立语音连接。"""
    client = TestClient(
        _create_app(
            StubRealtimeConnection([]),
            allowed_origins=("https://chat.example.com",),
        ),
    )

    with pytest.raises(WebSocketDisconnect) as raised:
        with client.websocket_connect(
            "/api/v1/voice/realtime",
            headers={"origin": "https://attacker.example.com"},
        ):
            pass

    assert raised.value.code == 1008


def test_realtime_voice_closes_invalid_audio_event_with_policy_error() -> None:
    """非 PCM16 或超出公共协议的音频事件应终止连接。"""
    connection = StubRealtimeConnection(
        [{"type": "session.updated"}],
        close_after_events=False,
    )
    client = TestClient(_create_app(connection))

    with client.websocket_connect(
        "/api/v1/voice/realtime",
        headers={"origin": "http://testserver"},
    ) as websocket:
        assert websocket.receive_json() == {"type": "session.ready"}
        websocket.send_json({"type": "audio.append", "audio": "YQ=="})
        assert websocket.receive_json() == {
            "type": "error",
            "code": "invalid_client_event",
            "message": "PCM16 音频帧必须包含完整采样点。",
        }
        with pytest.raises(WebSocketDisconnect) as raised:
            websocket.receive_json()

    assert raised.value.code == 1008

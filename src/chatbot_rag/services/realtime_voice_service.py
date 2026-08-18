"""实时双工语音会话与 AgentScope 工具调用适配。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from typing import Any

from agentscope.message import TextBlock, ToolCallBlock
from agentscope.state import AgentState
from agentscope.tool import Toolkit, ToolResponse
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from chatbot_rag.models import (
    RealtimeVoiceConnection,
    RealtimeVoiceConnectionFactory,
)
from chatbot_rag.schemas import (
    MAX_REALTIME_AUDIO_BYTES,
    RealtimeAudioAppendEvent,
)

logger = logging.getLogger(__name__)

MAX_TOOL_OUTPUT_CHARACTERS = 50_000

VOICE_SYSTEM_PROMPT = """你是一个简洁的中文实时语音助手。
涉及项目资料、产品功能、操作步骤或其他私有事实时，必须先调用 search_knowledge；
明确无关的通用问答、写作、翻译或创意任务不调用。无法确定时优先检索。
知识库回答只能使用当前轮工具返回的直接证据；证据不足时明确说知识库中未检索到足够信息，
不得用常识补全。默认用适合朗读的短句回答，操作类问题最多说 3 至 5 个核心步骤。
使用知识库时在回答末尾自然说出最多 3 个实际采用的来源文件名。
不要朗读工具名称、调用过程、Markdown 标记或 chatbot-media 图片标记。"""


class RealtimeVoiceClientProtocolError(ValueError):
    """浏览器提交的实时语音事件不符合公共协议。"""


class RealtimeVoiceUpstreamError(RuntimeError):
    """百炼实时语音连接或事件处理失败。"""


class RealtimeVoiceService:
    """在浏览器与单个 Qwen-Audio Realtime 会话之间建立受控桥接。"""

    def __init__(
        self,
        *,
        connection_factory: RealtimeVoiceConnectionFactory,
        toolkit: Toolkit,
        voice_name: str,
        allowed_origins: tuple[str, ...],
    ) -> None:
        """保存连接工厂、知识库工具和浏览器来源允许列表。"""
        self._connection_factory = connection_factory
        self._toolkit = toolkit
        self._voice_name = voice_name
        self._allowed_origins = frozenset(allowed_origins)

    def is_origin_allowed(self, origin: str | None) -> bool:
        """判断浏览器 WebSocket 来源是否在显式允许列表内。"""
        return origin in self._allowed_origins

    async def run(self, browser: WebSocket) -> None:
        """接受浏览器连接并运行一个独立的实时语音会话。

        Args:
            browser: 已通过 Origin 校验、尚未接受的 FastAPI WebSocket。
        """
        await browser.accept()
        try:
            tool_schemas = await self._toolkit.get_tool_schemas()
            async with self._connection_factory.connect() as upstream:
                send_lock = asyncio.Lock()
                await self._send_upstream(
                    upstream,
                    send_lock,
                    {
                        "type": "session.update",
                        "session": {
                            "modalities": ["audio", "text"],
                            "voice": self._voice_name,
                            "instructions": VOICE_SYSTEM_PROMPT,
                            "input_audio_format": "pcm",
                            "output_audio_format": "pcm",
                            "max_history_turns": 20,
                            "tools": tool_schemas,
                            "turn_detection": {"type": "smart_turn"},
                        },
                    },
                )
                await self._bridge(browser, upstream, send_lock)
        except RealtimeVoiceClientProtocolError as error:
            await self._send_browser_error(
                browser,
                code="invalid_client_event",
                message=str(error),
            )
            await self._close_browser(browser, code=1008)
            return
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("实时语音会话失败")
            await self._send_browser_error(
                browser,
                code="voice_service_unavailable",
                message="实时语音服务暂时不可用，请稍后重试。",
            )
        await self._close_browser(browser, code=1000)

    async def _bridge(
        self,
        browser: WebSocket,
        upstream: RealtimeVoiceConnection,
        send_lock: asyncio.Lock,
    ) -> None:
        """并发传输上下行事件，任一方向结束即回收另一方向。"""
        browser_task = asyncio.create_task(
            self._relay_browser_audio(browser, upstream, send_lock),
        )
        upstream_task = asyncio.create_task(
            self._relay_upstream_events(browser, upstream, send_lock),
        )
        done, pending = await asyncio.wait(
            {browser_task, upstream_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            error = task.exception()
            if error is not None:
                raise error

    async def _relay_browser_audio(
        self,
        browser: WebSocket,
        upstream: RealtimeVoiceConnection,
        send_lock: asyncio.Lock,
    ) -> None:
        """校验浏览器 PCM 帧并只转发允许的音频追加事件。"""
        while True:
            try:
                payload = await browser.receive_json()
                event = RealtimeAudioAppendEvent.model_validate(payload)
                audio = base64.b64decode(event.audio, validate=True)
            except WebSocketDisconnect:
                return
            except (ValidationError, ValueError, binascii.Error) as error:
                raise RealtimeVoiceClientProtocolError(
                    "音频事件格式无效。",
                ) from error
            if not audio or len(audio) > MAX_REALTIME_AUDIO_BYTES:
                raise RealtimeVoiceClientProtocolError(
                    "单个音频帧必须在 1 至 6400 字节之间。",
                )
            if len(audio) % 2 != 0:
                raise RealtimeVoiceClientProtocolError(
                    "PCM16 音频帧必须包含完整采样点。",
                )
            await self._send_upstream(
                upstream,
                send_lock,
                {
                    "type": "input_audio_buffer.append",
                    "audio": event.audio,
                },
            )

    async def _relay_upstream_events(
        self,
        browser: WebSocket,
        upstream: RealtimeVoiceConnection,
        send_lock: asyncio.Lock,
    ) -> None:
        """把百炼事件转换为不泄漏供应商内部结构的公共事件。"""
        has_tool_output = False
        async for raw_event in upstream:
            event = self._decode_upstream_event(raw_event)
            event_type = event.get("type")
            if event_type == "session.updated":
                await browser.send_json({"type": "session.ready"})
            elif event_type == "input_audio_buffer.speech_started":
                await browser.send_json({"type": "input.speech_started"})
            elif event_type == "input_audio_buffer.speech_stopped":
                await browser.send_json({"type": "input.speech_stopped"})
            elif event_type == (
                "conversation.item.input_audio_transcription.delta"
            ):
                await browser.send_json(
                    {
                        "type": "transcript.user.delta",
                        "text": self._require_string(event, "text"),
                        "stash": self._optional_string(event, "stash"),
                    },
                )
            elif event_type == (
                "conversation.item.input_audio_transcription.completed"
            ):
                await browser.send_json(
                    {
                        "type": "transcript.user.done",
                        "transcript": self._require_string(
                            event,
                            "transcript",
                        ),
                    },
                )
            elif event_type == "response.audio_transcript.delta":
                await browser.send_json(
                    {
                        "type": "transcript.assistant.delta",
                        "delta": self._require_string(event, "delta"),
                    },
                )
            elif event_type == "response.audio_transcript.done":
                await browser.send_json(
                    {
                        "type": "transcript.assistant.done",
                        "transcript": self._require_string(
                            event,
                            "transcript",
                        ),
                    },
                )
            elif event_type == "response.audio.delta":
                await browser.send_json(
                    {
                        "type": "audio.delta",
                        "audio": self._require_string(event, "delta"),
                    },
                )
            elif event_type == "response.function_call_arguments.done":
                await self._handle_tool_call(
                    browser,
                    upstream,
                    send_lock,
                    event,
                )
                has_tool_output = True
            elif event_type == "response.done":
                if has_tool_output:
                    has_tool_output = False
                    await self._send_upstream(
                        upstream,
                        send_lock,
                        {
                            "type": "response.create",
                            "response": {
                                "modalities": ["audio", "text"],
                            },
                        },
                    )
                else:
                    await browser.send_json({"type": "response.done"})
            elif event_type == "error":
                error = event.get("error")
                code = error.get("code") if isinstance(error, dict) else None
                logger.error("百炼实时语音返回错误，code=%s", code)
                raise RealtimeVoiceUpstreamError(
                    "百炼实时语音返回错误事件",
                )

    async def _handle_tool_call(
        self,
        browser: WebSocket,
        upstream: RealtimeVoiceConnection,
        send_lock: asyncio.Lock,
        event: dict[str, Any],
    ) -> None:
        """通过 AgentScope Toolkit 执行函数并写回标准 Function Call 结果。"""
        call_id = self._require_string(event, "call_id")
        name = self._require_string(event, "name")
        arguments = self._require_string(event, "arguments")
        await browser.send_json({"type": "tool.started"})
        try:
            output = await self._call_tool(call_id, name, arguments)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("实时语音知识库工具执行失败，tool=%s", name)
            output = json.dumps(
                {
                    "state": "error",
                    "content": "知识库检索失败，请向用户如实说明。",
                },
                ensure_ascii=False,
            )
        await self._send_upstream(
            upstream,
            send_lock,
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            },
        )
        await browser.send_json({"type": "tool.completed"})

    async def _call_tool(
        self,
        call_id: str,
        name: str,
        arguments: str,
    ) -> str:
        """调用 AgentScope 工具并序列化模型可消费的最终结果。"""
        final_response: ToolResponse | None = None
        async for chunk in self._toolkit.call_tool(
            ToolCallBlock(id=call_id, name=name, input=arguments),
            AgentState(),
        ):
            if isinstance(chunk, ToolResponse):
                final_response = chunk
        if final_response is None:
            raise RealtimeVoiceUpstreamError("知识库工具未返回最终结果")
        content = "\n".join(
            block.text
            for block in final_response.content
            if isinstance(block, TextBlock) and block.text
        )[:MAX_TOOL_OUTPUT_CHARACTERS]
        return json.dumps(
            {
                "state": final_response.state.value,
                "content": content,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _decode_upstream_event(raw_event: str | bytes) -> dict[str, Any]:
        """解析百炼 JSON 文本事件并拒绝二进制或非对象消息。"""
        if not isinstance(raw_event, str):
            raise RealtimeVoiceUpstreamError("百炼返回了非文本事件")
        try:
            event = json.loads(raw_event)
        except json.JSONDecodeError as error:
            raise RealtimeVoiceUpstreamError(
                "百炼返回了无效 JSON 事件",
            ) from error
        if not isinstance(event, dict) or not isinstance(
            event.get("type"),
            str,
        ):
            raise RealtimeVoiceUpstreamError("百炼事件缺少有效类型")
        return event

    @staticmethod
    def _require_string(event: dict[str, Any], field: str) -> str:
        """读取上游必需字符串字段。"""
        value = event.get(field)
        if not isinstance(value, str):
            raise RealtimeVoiceUpstreamError(
                f"百炼事件字段 {field} 无效",
            )
        return value

    @staticmethod
    def _optional_string(event: dict[str, Any], field: str) -> str:
        """读取上游可选字符串字段，缺省时返回空文本。"""
        value = event.get(field, "")
        if not isinstance(value, str):
            raise RealtimeVoiceUpstreamError(
                f"百炼事件字段 {field} 无效",
            )
        return value

    @staticmethod
    async def _send_upstream(
        upstream: RealtimeVoiceConnection,
        send_lock: asyncio.Lock,
        event: dict[str, Any],
    ) -> None:
        """串行发送上游事件，避免音频与工具结果并发写入。"""
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        async with send_lock:
            await upstream.send(payload)

    @staticmethod
    async def _send_browser_error(
        browser: WebSocket,
        *,
        code: str,
        message: str,
    ) -> None:
        """仅在浏览器仍连接时发送受控错误。"""
        if browser.application_state == WebSocketState.CONNECTED:
            await browser.send_json(
                {"type": "error", "code": code, "message": message},
            )

    @staticmethod
    async def _close_browser(browser: WebSocket, *, code: int) -> None:
        """仅在浏览器仍连接时关闭 WebSocket。"""
        if browser.application_state == WebSocketState.CONNECTED:
            await browser.close(code=code)

"""AgentScope 事件到 Web NDJSON 协议的转换。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypeAlias, cast

from agentscope.event import (
    AgentEvent,
    HintBlockEvent,
    ReplyEndEvent,
    ReplyFinishedReason,
    ReplyStartEvent,
    TextBlockDeltaEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import TextBlock
from pydantic import BaseModel

from chatbot_rag.rag import (
    MediaAssetError,
    MediaAssetStore,
)
from chatbot_rag.rag.media_assets import extract_media_asset_ids
from chatbot_rag.schemas import (
    ChatErrorEvent,
    ChatImagePartEvent,
    ChatMessageEndEvent,
    ChatMessageStartEvent,
    ChatTextDeltaEvent,
)

LOGGER = logging.getLogger(__name__)
MAX_REPLY_IMAGES = 3
_MEDIA_REFERENCE_OPENING = '<chatbot-media asset-id="'
_MEDIA_REFERENCE_CLOSING = '" />'
_MEDIA_REFERENCE_TAG = "<chatbot-media"
_HEX_DIGITS = frozenset("0123456789abcdef")
_KNOWLEDGE_SEARCH_TOOL_NAME = "search_knowledge"


@dataclass(frozen=True, slots=True)
class _MediaReference:
    """从模型文本中解析出的单个内部图片引用。"""

    asset_id: str


_StreamPart: TypeAlias = str | _MediaReference
_CandidateState: TypeAlias = Literal[
    "complete",
    "discard",
    "incomplete",
    "text",
]


class _InlineMediaParser:
    """跨任意文本增量边界解析内部图片引用。"""

    def __init__(self) -> None:
        """初始化空的流式解析状态。"""
        self._candidate: str | None = None
        self._discarding = False

    def feed(self, value: str) -> list[_StreamPart]:
        """消费一个文本增量并返回当前已确定的有序内容。"""
        parts: list[_StreamPart] = []
        text: list[str] = []

        for character in value:
            if self._discarding:
                if character == ">":
                    self._discarding = False
                continue

            if self._candidate is None:
                if character == "<":
                    _append_text_part(parts, text)
                    self._candidate = character
                else:
                    text.append(character)
                continue

            self._candidate += character
            state = _candidate_state(self._candidate)
            if state == "incomplete":
                continue
            if state == "complete":
                _append_text_part(parts, text)
                asset_id_start = len(_MEDIA_REFERENCE_OPENING)
                asset_id_end = -len(_MEDIA_REFERENCE_CLOSING)
                asset_id = self._candidate[asset_id_start:asset_id_end]
                parts.append(_MediaReference(asset_id=asset_id))
                self._candidate = None
                continue
            if state == "text":
                text.append(self._candidate)
                self._candidate = None
                continue

            self._candidate = None
            self._discarding = character != ">"

        _append_text_part(parts, text)
        return parts

    def finish(self) -> list[_StreamPart]:
        """结束解析，并仅返回不属于内部标记的普通尾部文本。"""
        candidate = self._candidate
        self._candidate = None
        self._discarding = False
        if candidate is None or candidate.startswith(_MEDIA_REFERENCE_TAG):
            return []
        return [candidate]


async def encode_chat_stream(
    events: AsyncIterator[AgentEvent],
    media_store: MediaAssetStore | None = None,
) -> AsyncIterator[bytes]:
    """将 AgentScope 事件转换为公共 NDJSON 流。

    Args:
        events: AgentScope 2.0.5 原生事件流。
        media_store: 用于解析检索媒体标记的图片资产仓库。

    Yields:
        每行一个 UTF-8 编码的 JSON 对象。
    """
    message_id: str | None = None
    hint_reply_id: str | None = None
    allowed_media_asset_ids: set[str] = set()
    emitted_media_asset_ids: set[str] = set()
    inline_media_parser = _InlineMediaParser()
    knowledge_tool_media_parsers: dict[str, _InlineMediaParser] = {}
    has_text_since_image = False

    try:
        async for event in events:
            if isinstance(event, HintBlockEvent):
                if message_id is not None and event.reply_id != message_id:
                    yield _encode_event(_protocol_error())
                    return
                if (
                    hint_reply_id is not None
                    and event.reply_id != hint_reply_id
                ):
                    yield _encode_event(_protocol_error())
                    return
                hint_reply_id = event.reply_id
                allowed_media_asset_ids.update(
                    _extract_hint_media_ids(event),
                )
                continue

            if isinstance(event, ReplyStartEvent):
                if message_id is not None:
                    yield _encode_event(_protocol_error())
                    return
                message_id = event.reply_id
                if (
                    hint_reply_id is not None
                    and hint_reply_id != message_id
                ):
                    yield _encode_event(_protocol_error())
                    return
                yield _encode_event(
                    ChatMessageStartEvent(message_id=message_id),
                )
                continue

            if isinstance(event, ToolResultStartEvent):
                if message_id is None or event.reply_id != message_id:
                    yield _encode_event(_protocol_error())
                    return
                if event.tool_call_name == _KNOWLEDGE_SEARCH_TOOL_NAME:
                    knowledge_tool_media_parsers[event.tool_call_id] = (
                        _InlineMediaParser()
                    )
                continue

            if isinstance(event, ToolResultTextDeltaEvent):
                if message_id is None or event.reply_id != message_id:
                    yield _encode_event(_protocol_error())
                    return
                parser = knowledge_tool_media_parsers.get(event.tool_call_id)
                if parser is not None:
                    allowed_media_asset_ids.update(
                        part.asset_id
                        for part in parser.feed(event.delta)
                        if isinstance(part, _MediaReference)
                    )
                continue

            if isinstance(event, ToolResultEndEvent):
                if message_id is None or event.reply_id != message_id:
                    yield _encode_event(_protocol_error())
                    return
                knowledge_tool_media_parsers.pop(event.tool_call_id, None)
                continue

            if isinstance(event, TextBlockDeltaEvent):
                if message_id is None or event.reply_id != message_id:
                    yield _encode_event(_protocol_error())
                    return
                if event.delta:
                    for part in inline_media_parser.feed(event.delta):
                        if (
                            isinstance(part, _MediaReference)
                            and not has_text_since_image
                        ):
                            continue
                        public_event = _public_part_event(
                            part,
                            message_id=message_id,
                            allowed_asset_ids=allowed_media_asset_ids,
                            emitted_asset_ids=emitted_media_asset_ids,
                            media_store=media_store,
                        )
                        if public_event is not None:
                            yield _encode_event(public_event)
                            if isinstance(public_event, ChatImagePartEvent):
                                has_text_since_image = False
                            elif public_event.text.strip():
                                has_text_since_image = True
                continue

            if isinstance(event, ReplyEndEvent):
                if message_id is None or event.reply_id != message_id:
                    yield _encode_event(_protocol_error())
                    return
                if event.finished_reason == ReplyFinishedReason.COMPLETED:
                    for part in inline_media_parser.finish():
                        if (
                            isinstance(part, _MediaReference)
                            and not has_text_since_image
                        ):
                            continue
                        public_event = _public_part_event(
                            part,
                            message_id=message_id,
                            allowed_asset_ids=allowed_media_asset_ids,
                            emitted_asset_ids=emitted_media_asset_ids,
                            media_store=media_store,
                        )
                        if public_event is not None:
                            yield _encode_event(public_event)
                            if isinstance(public_event, ChatImagePartEvent):
                                has_text_since_image = False
                            elif public_event.text.strip():
                                has_text_since_image = True
                    yield _encode_event(
                        ChatMessageEndEvent(message_id=message_id),
                    )
                else:
                    yield _encode_event(
                        ChatErrorEvent(
                            code="agent_error",
                            message="助手未能完成本次回复，请重试。",
                        ),
                    )
                return
    except Exception:
        LOGGER.exception("AgentScope 流式回复处理失败")
        yield _encode_event(
            ChatErrorEvent(
                code="agent_error",
                message="助手服务暂时不可用，请稍后重试。",
            ),
        )
        return

    yield _encode_event(
        ChatErrorEvent(
            code="incomplete_stream",
            message="回复流意外中断，请重试。",
        ),
    )


def _protocol_error() -> ChatErrorEvent:
    """返回不暴露内部事件结构的协议错误。"""
    return ChatErrorEvent(
        code="protocol_error",
        message="回复流格式无效，请重试。",
    )


def _extract_hint_media_ids(event: HintBlockEvent) -> list[str]:
    """只从公开检索提示的文本块中读取项目媒体标记。"""
    if isinstance(event.hint, str):
        values = [event.hint]
    else:
        values = [
            block.text
            for block in event.hint
            if isinstance(block, TextBlock)
        ]
    return list(
        dict.fromkeys(
            asset_id
            for value in values
            for asset_id in extract_media_asset_ids(value)
        ),
    )


def _candidate_state(candidate: str) -> _CandidateState:
    """判断当前候选文本是否可能组成一个完整媒体标记。"""
    if _MEDIA_REFERENCE_OPENING.startswith(candidate):
        return "incomplete"
    if not candidate.startswith(_MEDIA_REFERENCE_OPENING):
        return "text"

    payload_start = len(_MEDIA_REFERENCE_OPENING)
    payload = candidate[payload_start:]
    asset_id = payload[:64]
    if len(asset_id) < 64:
        return (
            "incomplete"
            if all(character in _HEX_DIGITS for character in asset_id)
            else "discard"
        )
    if any(character not in _HEX_DIGITS for character in asset_id):
        return "discard"

    closing = payload[64:]
    if not _MEDIA_REFERENCE_CLOSING.startswith(closing):
        return "discard"
    if closing == _MEDIA_REFERENCE_CLOSING:
        return "complete"
    return "incomplete"


def _append_text_part(parts: list[_StreamPart], text: list[str]) -> None:
    """把已确认的连续普通文本追加为一个流内容片段。"""
    if text:
        parts.append("".join(text))
        text.clear()


def _public_part_event(
    part: _StreamPart,
    message_id: str,
    allowed_asset_ids: set[str],
    emitted_asset_ids: set[str],
    media_store: MediaAssetStore | None,
) -> ChatTextDeltaEvent | ChatImagePartEvent | None:
    """把解析结果转换为文本或经本轮检索授权的图片事件。"""
    if isinstance(part, str):
        if not part:
            return None
        return ChatTextDeltaEvent(message_id=message_id, text=part)

    if (
        media_store is None
        or part.asset_id not in allowed_asset_ids
        or part.asset_id in emitted_asset_ids
        or len(emitted_asset_ids) >= MAX_REPLY_IMAGES
    ):
        return None

    try:
        descriptor = media_store.describe(part.asset_id)
        url = media_store.public_url(part.asset_id)
    except MediaAssetError:
        LOGGER.exception("检索结果引用了不可用的图片资产")
        return None

    emitted_asset_ids.add(part.asset_id)
    return ChatImagePartEvent(
        message_id=message_id,
        url=url,
        filename=descriptor.filename,
    )


def _encode_event(event: BaseModel) -> bytes:
    """将单个公共事件编码为一行 NDJSON。"""
    payload = cast(str, event.model_dump_json())
    return (payload + "\n").encode("utf-8")

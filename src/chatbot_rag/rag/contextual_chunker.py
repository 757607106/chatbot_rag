"""为最终检索块补充所属章节的稳定上下文。"""

from __future__ import annotations

from typing import cast

from agentscope.message import TextBlock
from agentscope.rag import Chunk, ChunkerBase, Section

RETRIEVAL_CONTEXT_KEY = "retrieval_context"
PAGE_CONTEXT_KEY = "page"
SLIDE_CONTEXT_KEY = "slide"
SHEET_CONTEXT_KEY = "sheet"
SOURCE_CONTEXT_LABEL = "文档来源"
PAGE_CONTEXT_LABEL = "页码"
SLIDE_CONTEXT_LABEL = "幻灯片"
SHEET_CONTEXT_LABEL = "工作表"


class ContextPreservingChunker(ChunkerBase):  # type: ignore[misc]
    """包装现有切块器，并让每个文本块保留来源和章节上下文。"""

    def __init__(self, chunker: ChunkerBase) -> None:
        """使用指定的 AgentScope 切块器初始化包装器。

        Args:
            chunker: 负责执行实际长度切分的底层切块器。
        """
        self._chunker = chunker

    async def chunk(self, sections: list[Section]) -> list[Chunk]:
        """切分章节，并把稳定检索上下文补到每个文本块。

        Args:
            sections: 解析器输出的自然章节。

        Returns:
            保持原始顺序、编号和媒体块行为的最终检索块。
        """
        contextualized_sections = [
            _prepend_section_context(section) for section in sections
        ]
        chunks = cast(
            list[Chunk],
            await self._chunker.chunk(contextualized_sections),
        )
        for chunk in chunks:
            _ensure_chunk_context(chunk)
        return chunks


def _prepend_section_context(section: Section) -> Section:
    """复制章节，并在长度切分前为文本添加一次来源上下文。"""
    copied = section.model_copy(deep=True)
    if not isinstance(copied.content, TextBlock):
        return copied

    context = _build_context(copied.source, copied.metadata)
    if context:
        copied.content.text = _join_context(context, copied.content.text)
    return copied


def _ensure_chunk_context(chunk: Chunk) -> None:
    """为同一章节中被二次切开的后续块重复补充来源上下文。"""
    if not isinstance(chunk.content, TextBlock):
        return

    context = _build_context(chunk.source, chunk.metadata)
    if not context:
        return

    prefix = f"{context}\n\n"
    if chunk.content.text != context and not chunk.content.text.startswith(
        prefix,
    ):
        chunk.content.text = _join_context(context, chunk.content.text)


def _build_context(source: str, metadata: dict[str, object]) -> str:
    """由来源、页码和解析器上下文构建每个块都具备的稳定范围。"""
    values = [f"{SOURCE_CONTEXT_LABEL}：{source}"]
    page = metadata.get(PAGE_CONTEXT_KEY)
    if isinstance(page, int) and not isinstance(page, bool) and page > 0:
        values.append(f"{PAGE_CONTEXT_LABEL}：{page}")
    slide = metadata.get(SLIDE_CONTEXT_KEY)
    if isinstance(slide, int) and not isinstance(slide, bool) and slide > 0:
        values.append(f"{SLIDE_CONTEXT_LABEL}：{slide}")
    sheet = metadata.get(SHEET_CONTEXT_KEY)
    if isinstance(sheet, str) and sheet.strip():
        values.append(f"{SHEET_CONTEXT_LABEL}：{sheet.strip()}")
    retrieval_context = metadata.get(RETRIEVAL_CONTEXT_KEY)
    if isinstance(retrieval_context, str) and retrieval_context.strip():
        values.append(retrieval_context.strip())
    return "\n".join(values)


def _join_context(context: str, text: str) -> str:
    """用稳定空行连接章节标题与正文。"""
    normalized_text = text.strip()
    if not normalized_text or normalized_text == context:
        return context
    if normalized_text.startswith(f"{context}\n\n"):
        return normalized_text
    return f"{context}\n\n{normalized_text}"

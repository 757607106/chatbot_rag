"""将 Markdown、Word 和 PDF 图片转换为可检索媒体引用。"""

from __future__ import annotations

import base64
import io
import logging
import os
import re
from pathlib import Path

from agentscope.message import Base64Source, DataBlock, TextBlock, URLSource
from agentscope.rag import ParserBase, Section, WordParser
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from chatbot_rag.rag.media_assets import (
    MediaAssetError,
    MediaAssetStore,
    format_media_reference,
)
from chatbot_rag.rag.contextual_chunker import RETRIEVAL_CONTEXT_KEY

_logger = logging.getLogger(__name__)

_MARKDOWN_IMAGE_PATTERN = re.compile(
    r"!\[(?P<alt>[^\]\r\n]*)\]"
    r"\(\s*(?P<url>https?://[^\s)]+)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)",
)
_MARKDOWN_HEADING_PATTERN = re.compile(
    r"^(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$",
)
_MARKDOWN_FENCE_PATTERN = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})",
)


class MarkdownMediaParser(ParserBase):  # type: ignore[misc]
    """解析 Markdown 文本并登记其中的远程图片。"""

    supported_media_types = ["text/markdown"]

    def __init__(self, media_store: MediaAssetStore) -> None:
        """使用指定图片资产仓库初始化解析器。"""
        self._media_store = media_store

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """返回 Markdown 文件扩展名。"""
        return [".markdown", ".md"]

    async def parse(
        self,
        file: bytes | str,
        filename: str,
    ) -> list[Section]:
        """解析文本，登记图片并按 Markdown 标题层级建立自然章节。

        Args:
            file: UTF-8 Markdown 字节、文本内容或文件路径。
            filename: 用于引用展示的相对文件名。

        Returns:
            携带完整标题路径和内部媒体标记的有序章节。
        """
        text = _read_utf8(file, filename)
        materialized_text = _replace_markdown_images(
            text,
            filename=filename,
            media_store=self._media_store,
        )
        return _split_markdown_by_heading(materialized_text, filename)


def _replace_markdown_images(
    text: str,
    filename: str,
    media_store: MediaAssetStore,
) -> str:
    """把代码围栏外的远程 Markdown 图片原位替换为内部媒体引用。

    不符合安全约束（协议、主机、端口等）的远程图片会被跳过，
    不影响文档文本内容的索引。
    """
    values: list[str] = []
    fence_marker: str | None = None
    ordinal = 0
    for line in text.splitlines(keepends=True):
        fence_match = _MARKDOWN_FENCE_PATTERN.match(line)
        if fence_match is not None:
            marker = fence_match.group("fence")
            if fence_marker is None:
                fence_marker = marker
            elif marker[0] == fence_marker[0] and len(marker) >= len(
                fence_marker,
            ):
                fence_marker = None
            values.append(line)
            continue
        if fence_marker is not None:
            values.append(line)
            continue

        cursor = 0
        for match in _MARKDOWN_IMAGE_PATTERN.finditer(line):
            values.append(line[cursor:match.start()])
            try:
                asset_id = media_store.register_remote(
                    url=match.group("url"),
                    filename=match.group("alt"),
                    identity=f"{filename}#markdown-image-{ordinal}",
                )
            except MediaAssetError:
                _logger.warning(
                    "跳过不允许的远程图片：%s（文件 %s）",
                    match.group("url"),
                    filename,
                )
                ordinal += 1
                cursor = match.end()
                continue
            ordinal += 1
            values.append(format_media_reference(asset_id))
            cursor = match.end()
        values.append(line[cursor:])
    return "".join(values)


def _split_markdown_by_heading(text: str, filename: str) -> list[Section]:
    """按标题建立自然章节，并把完整标题路径写入检索元数据。"""
    sections: list[Section] = []
    heading_path: list[tuple[int, str]] = []
    active_context = ""
    content_lines: list[str] = []
    fence_marker: str | None = None

    for line in text.splitlines(keepends=True):
        fence_match = _MARKDOWN_FENCE_PATTERN.match(line)
        if fence_match is not None:
            marker = fence_match.group("fence")
            if fence_marker is None:
                fence_marker = marker
            elif marker[0] == fence_marker[0] and len(marker) >= len(
                fence_marker,
            ):
                fence_marker = None
            content_lines.append(line)
            continue

        heading_match = (
            None if fence_marker is not None else _MARKDOWN_HEADING_PATTERN.match(
                line.rstrip("\r\n"),
            )
        )
        if heading_match is None:
            content_lines.append(line)
            continue

        _append_markdown_section(
            sections,
            content_lines,
            source=filename,
            retrieval_context=active_context,
        )
        content_lines = []
        level = len(heading_match.group("marks"))
        title = heading_match.group("title").strip()
        while heading_path and heading_path[-1][0] >= level:
            heading_path.pop()
        heading_path.append((level, f"{'#' * level} {title}"))
        active_context = "\n".join(value for _, value in heading_path)

    _append_markdown_section(
        sections,
        content_lines,
        source=filename,
        retrieval_context=active_context,
    )
    return sections


def _append_markdown_section(
    sections: list[Section],
    content_lines: list[str],
    source: str,
    retrieval_context: str,
) -> None:
    """在正文非空时追加一个携带标题路径的 Markdown 章节。"""
    content = "".join(content_lines).strip()
    if not content:
        return

    metadata = (
        {RETRIEVAL_CONTEXT_KEY: retrieval_context}
        if retrieval_context
        else {}
    )
    sections.append(
        Section(
            content=TextBlock(text=content),
            source=source,
            metadata=metadata,
        ),
    )


class WordMediaParser(ParserBase):  # type: ignore[misc]
    """保留 Word 文本顺序并将内嵌图片存入媒体仓库。"""

    supported_media_types = WordParser.supported_media_types

    def __init__(self, media_store: MediaAssetStore) -> None:
        """使用 AgentScope 2.0.5 Word parser 初始化。"""
        self._media_store = media_store
        self._parser = WordParser(include_image=True)

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """返回 Word 文档扩展名。"""
        return [".docx"]

    async def parse(
        self,
        file: bytes | str,
        filename: str,
    ) -> list[Section]:
        """解析 Word 文档并把图片数据替换为内部媒体标记。"""
        sections = await self._parser.parse(file=file, filename=filename)
        return _materialize_data_sections(
            sections,
            media_store=self._media_store,
            filename=filename,
        )


class PDFMediaParser(ParserBase):  # type: ignore[misc]
    """按页提取 PDF 文本和浏览器可显示的内嵌图片。"""

    supported_media_types = ["application/pdf"]

    def __init__(self, media_store: MediaAssetStore) -> None:
        """使用指定图片资产仓库初始化解析器。"""
        self._media_store = media_store

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """返回 PDF 文件扩展名。"""
        return [".pdf"]

    async def parse(
        self,
        file: bytes | str,
        filename: str,
    ) -> list[Section]:
        """每页输出一个文本段，并在页尾追加对应图片引用。

        Args:
            file: PDF 字节或本地文件路径。
            filename: 用于引用展示的相对文件名。

        Returns:
            按页排序的文本与媒体引用段落。

        Raises:
            ValueError: 输入无法作为 PDF 解析时抛出。
        """
        raw = Path(file).read_bytes() if isinstance(file, str) else file
        try:
            reader = PdfReader(io.BytesIO(raw))
        except PdfReadError as error:
            raise ValueError(
                f"Failed to parse {filename!r} as PDF: {error}",
            ) from error

        sections: list[Section] = []
        for page_number, page in enumerate(reader.pages, start=1):
            values = [page.extract_text() or ""]
            for ordinal, image in enumerate(page.images):
                display_name = (
                    f"{Path(filename).stem}-第{page_number}页-"
                    f"{image.name or f'图片{ordinal + 1}'}"
                )
                asset_id = self._media_store.register_embedded(
                    data=image.data,
                    filename=display_name,
                    identity=(
                        f"{filename}#pdf-page-{page_number}-image-{ordinal}"
                    ),
                )
                values.append(format_media_reference(asset_id))

            text = _join_content(values)
            if not text.strip():
                continue
            sections.append(
                Section(
                    content=TextBlock(text=text),
                    source=filename,
                    metadata={"page": page_number},
                ),
            )
        return sections


def _materialize_data_sections(
    sections: list[Section],
    media_store: MediaAssetStore,
    filename: str,
) -> list[Section]:
    """将有序 DataBlock 转成与最近文本段绑定的媒体标记。"""
    output: list[Section] = []
    pending_references: list[str] = []
    image_ordinal = 0
    for section in sections:
        if isinstance(section.content, TextBlock):
            content = _join_content(
                [*pending_references, section.content.text],
            )
            pending_references.clear()
            output.append(
                Section(
                    content=TextBlock(text=content),
                    source=section.source,
                    metadata=dict(section.metadata),
                ),
            )
            continue

        asset_id = _register_data_block(
            section.content,
            media_store=media_store,
            filename=filename,
            ordinal=image_ordinal,
        )
        image_ordinal += 1
        if asset_id is None:
            continue
        reference = format_media_reference(asset_id)
        if output:
            _append_reference(output[-1], reference)
        else:
            pending_references.append(reference)

    if pending_references:
        output.append(
            Section(
                content=TextBlock(
                    text=_join_content(
                        ["文档图片", *pending_references],
                    ),
                ),
                source=filename,
                metadata={},
            ),
        )
    return output


def _register_data_block(
    block: DataBlock,
    media_store: MediaAssetStore,
    filename: str,
    ordinal: int,
) -> str | None:
    """根据 DataBlock 源类型登记内嵌或远程图片。

    远程图片不符合安全约束时返回 None，由调用方跳过。
    """
    display_name = (
        f"{Path(filename).stem}-{block.name or f'图片{ordinal + 1}'}"
    )
    identity = f"{filename}#word-image-{ordinal}"
    if isinstance(block.source, Base64Source):
        try:
            data = base64.b64decode(block.source.data, validate=True)
        except ValueError as error:
            raise ValueError("Word 文档包含无效的图片编码。") from error
        return media_store.register_embedded(
            data=data,
            filename=display_name,
            identity=identity,
        )
    if isinstance(block.source, URLSource):
        try:
            return media_store.register_remote(
                url=str(block.source.url),
                filename=display_name,
                identity=identity,
            )
        except MediaAssetError:
            _logger.warning(
                "跳过不允许的远程图片：%s（文件 %s）",
                block.source.url,
                filename,
            )
            return None
    raise TypeError(f"Unsupported data source: {type(block.source).__name__}")


def _append_reference(section: Section, reference: str) -> None:
    """将媒体标记追加到已确认的文本段。"""
    if not isinstance(section.content, TextBlock):
        raise TypeError("media references can only be added to text sections")
    section.content.text = _join_content(
        [section.content.text, reference],
    )


def _join_content(values: list[str]) -> str:
    """用稳定空行连接非空文本与媒体标记。"""
    return "\n\n".join(value.strip() for value in values if value.strip())


def _read_utf8(file: bytes | str, filename: str) -> str:
    """按 AgentScope TextParser 约定读取 UTF-8 文本。"""
    if isinstance(file, str):
        raw = Path(file).read_bytes() if os.path.isfile(file) else None
        if raw is None:
            return file
    else:
        raw = file
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(
            f"Failed to decode {filename!r} as UTF-8: {error}",
        ) from error

"""本地文档解析、切块与幂等索引。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from agentscope.message import TextBlock
from agentscope.rag import (
    Chunk,
    ChunkerBase,
    DocumentSummary,
    ExcelParser,
    KnowledgeBase,
    ParserBase,
    PDFParser,
    PPTParser,
    TextParser,
    WordParser,
)

from chatbot_rag.rag.media_assets import (
    MediaAssetStore,
    extract_media_asset_ids,
)
from chatbot_rag.rag.media_parsers import (
    MarkdownMediaParser,
    PDFMediaParser,
    WordMediaParser,
)

CONTENT_HASH_KEY = "content_sha256"
INGESTION_PIPELINE_KEY = "ingestion_pipeline"
INGESTION_PIPELINE_VERSION = "document-scope-context-v3"
SOURCE_PATH_KEY = "source_path"


class IngestionStage(Enum):
    """文档摄取过程向调用方报告的阶段。"""

    PARSING = "正在解析文件..."
    INDEXING = "正在创建索引..."


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    """一次目录摄取操作的统计结果。"""

    indexed_documents: int
    skipped_documents: int
    deleted_documents: int


@dataclass(frozen=True, slots=True)
class _PreparedDocument:
    """完成解析并等待写入知识库的文档。"""

    relative_path: str
    content_hash: str
    chunks: list[Chunk]
    media_asset_ids: set[str]
    previous_document_ids: tuple[str, ...]


class DocumentIngestor:
    """将目录中的受支持文件同步到 AgentScope 知识库。"""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        chunker: ChunkerBase,
        parsers: Mapping[str, ParserBase] | None = None,
        media_store: MediaAssetStore | None = None,
    ) -> None:
        """使用知识库、切块器和可选解析器映射初始化摄取器。

        Args:
            knowledge_base: 目标 AgentScope 知识库。
            chunker: 将解析结果转换为最终索引块的切块器。
            parsers: 以小写文件扩展名为键的解析器映射。
            media_store: 可选的文档图片资产仓库。
        """
        self._knowledge_base = knowledge_base
        self._chunker = chunker
        self._media_store = media_store
        if parsers is None:
            text_parser = TextParser()
            powerpoint_parser = PPTParser(
                include_image=False,
                separate_table=False,
                table_format="markdown",
            )
            excel_parser = ExcelParser(
                include_sheet_names=True,
                include_cell_coordinates=False,
                include_image=False,
                separate_sheet=True,
                table_format="markdown",
            )
            if media_store is None:
                markdown_parser: ParserBase = text_parser
                pdf_parser: ParserBase = PDFParser()
                word_parser: ParserBase = WordParser(include_image=False)
            else:
                markdown_parser = MarkdownMediaParser(media_store)
                pdf_parser = PDFMediaParser(media_store)
                word_parser = WordMediaParser(media_store)
            parsers = {
                ".docx": word_parser,
                ".md": markdown_parser,
                ".markdown": markdown_parser,
                ".pdf": pdf_parser,
                ".pptx": powerpoint_parser,
                ".txt": text_parser,
                ".xls": excel_parser,
                ".xlsx": excel_parser,
            }
        self._parsers = dict(parsers)

    async def ingest_directory(
        self,
        directory: Path,
        progress_callback: Callable[[IngestionStage], None] | None = None,
    ) -> IngestionSummary:
        """解析目录中的文档，并只索引新增或发生变化的内容。

        Args:
            directory: 递归扫描的文档根目录。
            progress_callback: 可选的摄取阶段通知函数。

        Returns:
            新建索引、跳过未变化及同步删除文档的数量。

        Raises:
            FileNotFoundError: 文档目录不存在时抛出。
            NotADirectoryError: 配置路径不是目录时抛出。
        """
        if not directory.exists():
            raise FileNotFoundError(f"Document directory does not exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Document path is not a directory: {directory}")

        if progress_callback is not None:
            progress_callback(IngestionStage.PARSING)

        existing_by_source = await self._existing_documents_by_source()
        supported_files = self._iter_supported_files(directory)
        active_sources = {
            path.relative_to(directory).as_posix()
            for path in supported_files
        }
        prepared_documents: list[_PreparedDocument] = []
        document_ids_to_delete = {
            summary.document_id
            for source_path, versions in existing_by_source.items()
            if source_path not in active_sources
            for summary in versions
        }
        skipped_documents = 0

        for file_path in supported_files:
            relative_path = file_path.relative_to(directory).as_posix()
            content = await asyncio.to_thread(file_path.read_bytes)
            content_hash = hashlib.sha256(content).hexdigest()
            existing_versions = existing_by_source.get(relative_path, [])
            current_versions = [
                summary
                for summary in existing_versions
                if summary.metadata.get(CONTENT_HASH_KEY) == content_hash
                and summary.metadata.get(INGESTION_PIPELINE_KEY)
                == INGESTION_PIPELINE_VERSION
            ]

            media_is_current = (
                self._media_store is None
                or self._media_store.has_document(relative_path)
            )
            if current_versions and media_is_current:
                document_ids_to_delete.update(
                    summary.document_id
                    for summary in existing_versions
                    if summary.document_id
                    != current_versions[0].document_id
                )
                skipped_documents += 1
                continue

            parser = self._parsers[file_path.suffix.lower()]
            sections = await parser.parse(
                file=content,
                filename=relative_path,
            )
            chunks = _remove_empty_text_chunks(
                await self._chunker.chunk(sections),
            )
            media_asset_ids = _extract_chunk_media_asset_ids(chunks)
            if not chunks:
                document_ids_to_delete.update(
                    summary.document_id for summary in existing_versions
                )
                skipped_documents += 1
                if self._media_store is not None:
                    self._media_store.commit_document(relative_path, set())
                continue

            prepared_documents.append(
                _PreparedDocument(
                    relative_path=relative_path,
                    content_hash=content_hash,
                    chunks=chunks,
                    media_asset_ids=media_asset_ids,
                    previous_document_ids=tuple(
                        summary.document_id
                        for summary in existing_versions
                    ),
                ),
            )

        if progress_callback is not None:
            progress_callback(IngestionStage.INDEXING)

        for document in prepared_documents:
            document_id = _document_version_id(
                document.relative_path,
                document.content_hash,
                INGESTION_PIPELINE_VERSION,
            )
            await self._knowledge_base.insert_document(
                document.chunks,
                document_id=document_id,
                document_metadata={
                    SOURCE_PATH_KEY: document.relative_path,
                    CONTENT_HASH_KEY: document.content_hash,
                    INGESTION_PIPELINE_KEY: INGESTION_PIPELINE_VERSION,
                },
            )
            if self._media_store is not None:
                self._media_store.commit_document(
                    document.relative_path,
                    document.media_asset_ids,
                )
            document_ids_to_delete.update(
                document.previous_document_ids,
            )
            document_ids_to_delete.discard(document_id)

        for document_id in sorted(document_ids_to_delete):
            await self._knowledge_base.delete_document(document_id)

        if self._media_store is not None:
            self._media_store.prune_documents(active_sources)

        return IngestionSummary(
            indexed_documents=len(prepared_documents),
            skipped_documents=skipped_documents,
            deleted_documents=len(document_ids_to_delete),
        )

    async def _existing_documents_by_source(
        self,
    ) -> dict[str, list[DocumentSummary]]:
        """按摄取时记录的相对路径聚合已有文档摘要。"""
        documents_by_source: dict[str, list[DocumentSummary]] = {}
        for summary in await self._knowledge_base.list_documents():
            source_path = summary.metadata.get(SOURCE_PATH_KEY)
            if isinstance(source_path, str):
                documents_by_source.setdefault(source_path, []).append(summary)
        return documents_by_source

    def _iter_supported_files(self, directory: Path) -> list[Path]:
        """按稳定顺序返回目录中受支持的普通文件。"""
        return sorted(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in self._parsers
        )


def _document_version_id(
    relative_path: str,
    content_hash: str,
    pipeline_version: str,
) -> str:
    """根据相对路径和内容摘要生成稳定的文档版本标识。"""
    identity = (
        f"{relative_path}\0{content_hash}\0{pipeline_version}"
    ).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


def _remove_empty_text_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """移除空文本块，并恢复连续的块序号。"""
    filtered_chunks = [
        chunk
        for chunk in chunks
        if not isinstance(chunk.content, TextBlock)
        or bool(chunk.content.text.strip())
    ]
    for index, chunk in enumerate(filtered_chunks):
        chunk.chunk_index = index
        chunk.total_chunks = len(filtered_chunks)
    return filtered_chunks


def _extract_chunk_media_asset_ids(chunks: list[Chunk]) -> set[str]:
    """收集最终索引文本中引用的全部图片资产。"""
    asset_ids: set[str] = set()
    for chunk in chunks:
        if isinstance(chunk.content, TextBlock):
            asset_ids.update(extract_media_asset_ids(chunk.content.text))
    return asset_ids

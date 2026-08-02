"""单知识库文档管理、后台任务和召回诊断用例。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agentscope.message import TextBlock
from agentscope.rag import Chunk, DocumentSummary, KnowledgeBase

from chatbot_rag.rag import (
    CatalogConflictError,
    CatalogError,
    ChunkEditConflictError,
    DocumentIngestionError,
    DocumentIngestor,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    IngestionStage,
    JobOperation,
    KnowledgeCatalog,
    KnowledgeJobRecord,
    MediaAssetDescriptor,
    MediaAssetError,
    MediaAssetStore,
    QdrantChunkReader,
    RerankingKnowledgeBase,
    RetrievalTrace,
    content_hash,
)
from chatbot_rag.rag.document_ingestor import (
    CONTENT_HASH_KEY,
    INGESTION_PIPELINE_KEY,
    INGESTION_PIPELINE_VERSION,
    SOURCE_PATH_KEY,
)
from chatbot_rag.rag.media_assets import extract_media_asset_ids

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset(
    {".docx", ".md", ".markdown", ".pdf", ".pptx", ".txt", ".xls", ".xlsx"},
)
KNOWN_UNSUPPORTED_EXTENSIONS = frozenset({".doc", ".ppt"})
_COPY_CHUNK_BYTES = 1024 * 1024


class KnowledgeServiceError(RuntimeError):
    """知识库管理用例无法完成。"""


class InvalidDocumentUploadError(KnowledgeServiceError):
    """上传文件的名称、格式或大小不符合要求。"""


@dataclass(frozen=True, slots=True)
class ManagedDocument:
    """文档状态及其最近后台任务。"""

    document: DocumentRecord
    latest_job: KnowledgeJobRecord | None


@dataclass(frozen=True, slots=True)
class ManagedMediaReference:
    """切片中可安全展示的图片引用。"""

    asset_id: str
    filename: str
    url: str


@dataclass(frozen=True, slots=True)
class ManagedChunk:
    """管理界面可读取的真实索引切片。"""

    chunk_index: int
    total_chunks: int
    source: str
    content: str
    content_hash: str
    is_manually_edited: bool
    metadata: Mapping[str, object]
    media: tuple[ManagedMediaReference, ...]


@dataclass(frozen=True, slots=True)
class ManagedChunkPage:
    """一个逻辑文档的切片分页结果。"""

    items: tuple[ManagedChunk, ...]
    total: int
    offset: int
    limit: int


class KnowledgeManagementService:
    """组合目录、文件、AgentScope 知识库和单工作协程。"""

    def __init__(
        self,
        *,
        knowledge_base: KnowledgeBase,
        ingestor: DocumentIngestor,
        catalog: KnowledgeCatalog,
        chunk_reader: QdrantChunkReader,
        media_store: MediaAssetStore,
        knowledge_base_id: str,
        knowledge_base_name: str,
        media_document_prefix: str | None,
        documents_path: Path,
        versions_path: Path,
        max_upload_bytes: int,
    ) -> None:
        """绑定应用生命周期内共享的知识库管理依赖。"""
        self._knowledge_base = knowledge_base
        self._ingestor = ingestor
        self._catalog = catalog
        self._chunk_reader = chunk_reader
        self._media_store = media_store
        self._knowledge_base_id = knowledge_base_id
        self._knowledge_base_name = knowledge_base_name
        self._media_document_prefix = media_document_prefix
        self._documents_path = documents_path
        self._versions_path = versions_path
        self._max_upload_bytes = max_upload_bytes
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    @property
    def knowledge_base_id(self) -> str:
        """返回当前知识库的稳定标识。"""
        return self._knowledge_base_id

    @property
    def knowledge_base_name(self) -> str:
        """返回面向管理界面的知识库名称。"""
        return self._knowledge_base_name

    @property
    def knowledge_base(self) -> KnowledgeBase:
        """返回可绑定聊天或诊断链路的 AgentScope 知识库。"""
        return self._knowledge_base

    @property
    def max_upload_bytes(self) -> int:
        """返回 HTTP 层限长读取使用的单文件上限。"""
        return self._max_upload_bytes

    async def start(self) -> None:
        """初始化目录、吸收本地文件并恢复未完成任务。"""
        self._documents_path.mkdir(parents=True, exist_ok=True)
        self._versions_path.mkdir(parents=True, exist_ok=True)
        await self._catalog.initialize()
        await self._catalog.recover_interrupted_jobs()
        await self._reconcile_documents_directory()
        self._worker = asyncio.create_task(
            self._worker_loop(),
            name="knowledge-management-worker",
        )
        for job in await self._catalog.queued_jobs():
            await self._queue.put(job.job_id)

    async def stop(self) -> None:
        """等待当前任务结束并停止后台工作协程。"""
        if self._worker is None:
            return
        await self._queue.put(None)
        await self._worker
        self._worker = None

    async def list_documents(self) -> list[ManagedDocument]:
        """列出当前知识库中的全部管理文档。"""
        documents = await self._catalog.list_documents()
        return [
            ManagedDocument(
                document=document,
                latest_job=await self._catalog.latest_job_for_document(
                    document.document_id,
                ),
            )
            for document in documents
        ]

    async def get_document(self, document_id: str) -> ManagedDocument:
        """读取一个逻辑文档及其最近任务。"""
        document = await self._catalog.get_document(document_id)
        return ManagedDocument(
            document=document,
            latest_job=await self._catalog.latest_job_for_document(document_id),
        )

    async def get_job(self, job_id: str) -> KnowledgeJobRecord:
        """读取持久化后台任务。"""
        return await self._catalog.get_job(job_id)

    async def list_versions(
        self,
        document_id: str,
    ) -> list[DocumentVersionRecord]:
        """按时间倒序列出文档保留的原始文件版本。"""
        await self._catalog.get_document(document_id)
        return list(reversed(await self._catalog.list_versions(document_id)))

    async def upload_document(
        self,
        *,
        filename: str,
        media_type: str | None,
        content: bytes,
        replace: bool,
    ) -> tuple[DocumentRecord, KnowledgeJobRecord]:
        """保存不可变版本并排队执行索引。

        Args:
            filename: 浏览器提供的原始文件名，不允许包含目录。
            media_type: 浏览器声明的内容类型，仅用于界面展示。
            content: 经过 HTTP 层限长读取的原始文件字节。
            replace: 同名文档存在时是否明确替换。

        Returns:
            逻辑文档和新建后台任务。
        """
        safe_filename = _validate_filename(filename)
        extension = Path(safe_filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise InvalidDocumentUploadError(
                f"不支持的文档格式：{extension or '无扩展名'}",
            )
        if not content:
            raise InvalidDocumentUploadError("上传文件不能为空。")
        if len(content) > self._max_upload_bytes:
            limit_mb = self._max_upload_bytes // (1024 * 1024)
            raise InvalidDocumentUploadError(
                f"单个文件不能超过 {limit_mb} MB。",
            )

        content_hash = hashlib.sha256(content).hexdigest()
        storage_path = self._new_version_path(extension)
        await asyncio.to_thread(_atomic_write_bytes, storage_path, content)
        resolved_media_type = (
            (media_type or "").strip()
            or mimetypes.guess_type(safe_filename)[0]
            or "application/octet-stream"
        )
        try:
            document, _, job = await self._catalog.create_index_job(
                source_path=safe_filename,
                filename=safe_filename,
                media_type=resolved_media_type,
                size_bytes=len(content),
                content_hash=content_hash,
                storage_path=storage_path,
                replace=replace,
            )
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise
        await self._queue.put(job.job_id)
        return document, job

    async def reindex_document(self, document_id: str) -> KnowledgeJobRecord:
        """排队重新索引当前活动版本。"""
        job = await self._catalog.create_reindex_job(document_id)
        await self._queue.put(job.job_id)
        return job

    async def delete_document(self, document_id: str) -> KnowledgeJobRecord:
        """排队删除文档原文件、全部索引和内部版本。"""
        job = await self._catalog.create_delete_job(document_id)
        await self._queue.put(job.job_id)
        return job

    async def rollback_document(
        self,
        document_id: str,
        version_id: str,
    ) -> KnowledgeJobRecord:
        """把历史原文件版本排队重新索引为活动版本。"""
        job = await self._catalog.create_rollback_job(
            document_id,
            version_id,
        )
        await self._queue.put(job.job_id)
        return job

    async def update_chunk(
        self,
        document_id: str,
        chunk_index: int,
        *,
        content: str,
        expected_content_hash: str,
    ) -> ManagedChunk:
        """使用乐观并发控制重新嵌入一个活动文本切片。"""
        normalized_content = content.strip()
        if not normalized_content:
            raise KnowledgeServiceError("切片内容不能为空。")
        if len(normalized_content) > 100_000:
            raise KnowledgeServiceError("单个切片内容不能超过 100000 个字符。")
        document = await self._catalog.get_document(document_id)
        if (
            document.status != DocumentStatus.READY
            or document.active_vector_document_id is None
        ):
            raise CatalogConflictError("文档当前不可编辑，请等待后台任务完成。")
        try:
            edited = await self._chunk_reader.update_text_chunk(
                document.active_vector_document_id,
                chunk_index,
                content=normalized_content,
                expected_content_hash=expected_content_hash,
            )
        except ChunkEditConflictError as error:
            raise CatalogConflictError(str(error)) from error
        await self._catalog.record_chunk_edit(
            edit_id=edited.edit_id,
            document_id=document.document_id,
            vector_document_id=document.active_vector_document_id,
            chunk_index=chunk_index,
            before_hash=edited.before_hash,
            after_hash=edited.after_hash,
        )
        return self._managed_chunk(edited.chunk)

    async def list_chunks(
        self,
        document_id: str,
        *,
        offset: int,
        limit: int,
    ) -> ManagedChunkPage:
        """读取一个文档当前活动索引的最终切片。"""
        document = await self._catalog.get_document(document_id)
        if document.active_vector_document_id is None:
            raise KnowledgeServiceError("文档当前没有可浏览的活动索引。")
        page = await self._chunk_reader.list_chunks(
            document.active_vector_document_id,
            offset=offset,
            limit=limit,
        )
        items = [self._managed_chunk(chunk) for chunk in page.items]
        return ManagedChunkPage(
            items=tuple(items),
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )

    async def test_retrieval(
        self,
        *,
        query: str,
        top_k: int,
        candidate_top_k: int,
        score_threshold: float | None,
    ) -> RetrievalTrace:
        """执行与聊天相同的向量召回和重排序流程。"""
        normalized_query = query.strip()
        if not normalized_query:
            raise KnowledgeServiceError("测试问题不能为空。")
        if not isinstance(self._knowledge_base, RerankingKnowledgeBase):
            raise KnowledgeServiceError("当前知识库不支持重排序诊断。")
        return await self._knowledge_base.search_with_trace(
            [normalized_query],
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            score_threshold=score_threshold,
        )

    async def wait_for_idle(self) -> None:
        """等待已排队任务全部完成，仅供测试和受控停机使用。"""
        await self._queue.join()

    async def _worker_loop(self) -> None:
        """顺序执行文档变更，避免同一集合出现并发写入竞争。"""
        while True:
            job_id = await self._queue.get()
            try:
                if job_id is None:
                    return
                await self._process_job(job_id)
            finally:
                self._queue.task_done()

    async def _process_job(self, job_id: str) -> None:
        """执行单个索引、重建或删除任务并收敛状态。"""
        try:
            job = await self._catalog.get_job(job_id)
            await self._catalog.mark_job_running(job_id, "准备处理")
            if job.operation == JobOperation.DELETE:
                await self._process_delete(job)
            else:
                await self._process_index(job)
        except Exception as error:
            logger.exception("知识库后台任务失败：%s", job_id)
            public_message = _public_job_error(error)
            try:
                await self._catalog.fail_job(job_id, public_message)
            except CatalogError:
                logger.exception("无法持久化知识库任务失败状态：%s", job_id)

    async def _process_index(self, job: KnowledgeJobRecord) -> None:
        """激活原始版本、建立新索引并切换目录状态。"""
        if job.version_id is None:
            raise KnowledgeServiceError("索引任务缺少文档版本。")
        document = await self._catalog.get_document(job.document_id)
        version = await self._catalog.get_version(job.version_id)
        if not version.storage_path.is_file():
            raise KnowledgeServiceError("待索引的原始版本文件不存在。")

        previous_version = (
            await self._catalog.get_version(document.active_version_id)
            if document.active_version_id is not None
            else None
        )
        active_path = _resolve_managed_source(
            self._documents_path,
            document.source_path,
        )
        await self._catalog.update_job_stage(job.job_id, "正在准备原文件")
        await asyncio.to_thread(
            _atomic_copy,
            version.storage_path,
            active_path,
        )

        loop = asyncio.get_running_loop()
        stage_tasks: list[asyncio.Task[None]] = []

        def report_progress(stage: IngestionStage) -> None:
            """把同步阶段回调安全调度到当前事件循环。"""
            stage_tasks.append(
                loop.create_task(
                    self._catalog.update_job_stage(job.job_id, stage.value),
                ),
            )

        vector_document_id = job.job_id
        try:
            indexed = await self._ingestor.ingest_file(
                version.storage_path,
                document.source_path,
                vector_document_id,
                document_metadata={
                    "knowledge_base_id": self._knowledge_base_id,
                    "logical_document_id": document.document_id,
                    "document_version_id": version.version_id,
                    "original_filename": document.filename,
                    "size_bytes": version.size_bytes,
                },
                progress_callback=report_progress,
                media_document_key=self._media_document_key(
                    document.source_path,
                ),
            )
        except Exception:
            if stage_tasks:
                await asyncio.gather(*stage_tasks, return_exceptions=True)
            if previous_version is None:
                active_path.unlink(missing_ok=True)
            else:
                await asyncio.to_thread(
                    _atomic_copy,
                    previous_version.storage_path,
                    active_path,
                )
            raise

        if stage_tasks:
            await asyncio.gather(*stage_tasks, return_exceptions=True)

        await self._catalog.complete_index_job(
            job.job_id,
            vector_document_id=indexed.vector_document_id,
            chunk_count=indexed.chunk_count,
        )

    async def _process_delete(self, job: KnowledgeJobRecord) -> None:
        """删除向量、图片、活动文件和全部内部版本文件。"""
        document = await self._catalog.get_document(job.document_id)
        await self._catalog.update_job_stage(job.job_id, "正在删除索引")
        await self._ingestor.delete_source(
            document.source_path,
            media_document_key=self._media_document_key(
                document.source_path,
            ),
        )
        active_path = _resolve_managed_source(
            self._documents_path,
            document.source_path,
        )
        active_path.unlink(missing_ok=True)
        await self._catalog.update_job_stage(job.job_id, "正在删除原文件")
        for version in await self._catalog.list_versions(document.document_id):
            version.storage_path.unlink(missing_ok=True)
        await self._catalog.complete_delete_job(job.job_id)

    async def _reconcile_documents_directory(self) -> None:
        """把已有本地文件和 Qdrant 摘要吸收到持久化目录。"""
        summaries = await self._knowledge_base.list_documents()
        summaries_by_source: dict[str, list[DocumentSummary]] = {}
        for summary in summaries:
            source_path = summary.metadata.get(SOURCE_PATH_KEY)
            if isinstance(source_path, str):
                summaries_by_source.setdefault(source_path, []).append(summary)

        active_sources: set[str] = set()
        present_sources: set[str] = set()
        for file_path in self._iter_managed_files():
            source_path = file_path.relative_to(
                self._documents_path,
            ).as_posix()
            present_sources.add(source_path)
            extension = file_path.suffix.lower()
            if extension in KNOWN_UNSUPPORTED_EXTENSIONS:
                await self._catalog.register_unsupported_document(
                    source_path=source_path,
                    filename=file_path.name,
                    size_bytes=file_path.stat().st_size,
                )
                continue
            if extension not in SUPPORTED_EXTENSIONS:
                continue
            active_sources.add(source_path)
            existing = await self._catalog.get_document_by_source(source_path)
            if existing is not None and existing.status in {
                DocumentStatus.QUEUED,
                DocumentStatus.PROCESSING,
                DocumentStatus.DELETING,
            }:
                continue

            content = await asyncio.to_thread(file_path.read_bytes)
            content_hash = hashlib.sha256(content).hexdigest()
            matching_summary = next(
                (
                    summary
                    for summary in summaries_by_source.get(source_path, [])
                    if summary.metadata.get(CONTENT_HASH_KEY) == content_hash
                    and summary.metadata.get(INGESTION_PIPELINE_KEY)
                    == INGESTION_PIPELINE_VERSION
                ),
                None,
            )
            if (
                matching_summary is not None
                and self._media_store.has_document(
                    self._media_document_key(source_path),
                )
            ):
                if (
                    existing is None
                    or existing.status != DocumentStatus.READY
                    or existing.active_vector_document_id
                    != matching_summary.document_id
                ):
                    storage_path = self._new_version_path(extension)
                    await asyncio.to_thread(
                        _atomic_copy,
                        file_path,
                        storage_path,
                    )
                    await self._catalog.register_ready_document(
                        source_path=source_path,
                        filename=file_path.name,
                        media_type=(
                            mimetypes.guess_type(file_path.name)[0]
                            or "application/octet-stream"
                        ),
                        size_bytes=len(content),
                        content_hash=content_hash,
                        storage_path=storage_path,
                        vector_document_id=matching_summary.document_id,
                        chunk_count=matching_summary.chunk_count,
                    )
                continue

            if existing is not None and existing.active_version_id is not None:
                active_version = await self._catalog.get_version(
                    existing.active_version_id,
                )
                if active_version.content_hash == content_hash:
                    try:
                        await self._catalog.create_reindex_job(
                            existing.document_id,
                        )
                    except CatalogConflictError:
                        pass
                    continue

            storage_path = self._new_version_path(extension)
            await asyncio.to_thread(_atomic_copy, file_path, storage_path)
            try:
                await self._catalog.create_index_job(
                    source_path=source_path,
                    filename=file_path.name,
                    media_type=(
                        mimetypes.guess_type(file_path.name)[0]
                        or "application/octet-stream"
                    ),
                    size_bytes=len(content),
                    content_hash=content_hash,
                    storage_path=storage_path,
                    replace=existing is not None,
                )
            except CatalogConflictError:
                storage_path.unlink(missing_ok=True)

        for managed in await self._catalog.list_documents():
            document = managed
            if document.source_path in present_sources:
                continue
            if document.status in {
                DocumentStatus.QUEUED,
                DocumentStatus.PROCESSING,
                DocumentStatus.DELETING,
            }:
                continue
            try:
                await self._catalog.create_delete_job(document.document_id)
            except CatalogConflictError:
                pass

        known_sources = {
            document.source_path
            for document in await self._catalog.list_documents()
        }
        for source_path in summaries_by_source:
            if source_path not in active_sources and source_path not in known_sources:
                await self._ingestor.delete_source(
                    source_path,
                    media_document_key=self._media_document_key(source_path),
                )

    def _iter_managed_files(self) -> list[Path]:
        """返回受管目录内的普通文件，并排除版本存储。"""
        versions_root = self._versions_path.resolve()
        return sorted(
            path
            for path in self._documents_path.rglob("*")
            if path.is_file()
            and not path.resolve().is_relative_to(versions_root)
        )

    def _new_version_path(self, extension: str) -> Path:
        """生成不会暴露原文件名的不可变版本路径。"""
        return self._versions_path / f"{uuid.uuid4().hex}{extension}"

    def _media_document_key(self, source_path: str) -> str:
        """生成跨知识库不会碰撞的图片清单键。"""
        if self._media_document_prefix is None:
            return source_path
        return f"{self._media_document_prefix}/{source_path}"

    def _managed_chunk(self, chunk: Chunk) -> ManagedChunk:
        """把 Qdrant 切片转换为管理端可安全展示的结构。"""
        if isinstance(chunk.content, TextBlock):
            content = chunk.content.text
            asset_ids = extract_media_asset_ids(content)
        else:
            content = chunk.content.model_dump_json()
            asset_ids = []
        media = tuple(
            reference
            for asset_id in sorted(asset_ids)
            if (reference := self._describe_media(asset_id)) is not None
        )
        return ManagedChunk(
            chunk_index=chunk.chunk_index,
            total_chunks=chunk.total_chunks,
            source=chunk.source,
            content=content,
            content_hash=content_hash(content),
            is_manually_edited=isinstance(
                chunk.metadata.get("manual_edit_id"),
                str,
            ),
            metadata=dict(chunk.metadata),
            media=media,
        )

    def _describe_media(
        self,
        asset_id: str,
    ) -> ManagedMediaReference | None:
        """把内部媒体标识转换为可公开的管理界面引用。"""
        try:
            descriptor: MediaAssetDescriptor = self._media_store.describe(
                asset_id,
            )
        except MediaAssetError:
            return None
        return ManagedMediaReference(
            asset_id=descriptor.asset_id,
            filename=descriptor.filename,
            url=self._media_store.public_url(descriptor.asset_id),
        )


def _validate_filename(filename: str) -> str:
    """拒绝路径穿越、隐藏控制文件和过长名称。"""
    value = filename.strip()
    if (
        not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise InvalidDocumentUploadError("文件名无效。")
    if len(value) > 255:
        raise InvalidDocumentUploadError("文件名不能超过 255 个字符。")
    return value


def _resolve_managed_source(root: Path, source_path: str) -> Path:
    """解析受管文件路径并拒绝越过配置根目录。"""
    root_resolved = root.resolve()
    path = (root / source_path).resolve()
    if not path.is_relative_to(root_resolved):
        raise KnowledgeServiceError("文档路径越过了受管目录。")
    return path


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """在目标目录内原子写入不可变版本文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file_handle:
            file_handle.write(content)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _atomic_copy(source: Path, destination: Path) -> None:
    """通过同目录临时文件原子替换活动原文件。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    os.close(descriptor)
    try:
        with source.open("rb") as source_handle, temporary_path.open(
            "wb",
        ) as destination_handle:
            while chunk := source_handle.read(_COPY_CHUNK_BYTES):
                destination_handle.write(chunk)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _public_job_error(error: Exception) -> str:
    """把内部异常收敛为不包含凭据和服务响应的公开文案。"""
    if isinstance(error, (DocumentIngestionError, KnowledgeServiceError)):
        return str(error)
    return "文档处理失败，请检查文件内容或服务配置后重试。"

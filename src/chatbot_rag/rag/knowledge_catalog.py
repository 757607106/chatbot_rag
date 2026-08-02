"""知识库文档、内容版本与异步任务的 SQLite 目录。"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Callable, TypeVar, cast

_T = TypeVar("_T")


class CatalogError(RuntimeError):
    """知识库目录操作失败。"""


class CatalogConflictError(CatalogError):
    """文档名称冲突且调用方未明确允许替换。"""


class CatalogNotFoundError(CatalogError):
    """请求的文档、版本或任务不存在。"""


class DocumentStatus(str, Enum):
    """管理界面可见的文档生命周期状态。"""

    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    DELETING = "deleting"
    DELETED = "deleted"


class VersionStatus(str, Enum):
    """一个不可变文档版本的处理状态。"""

    QUEUED = "queued"
    PROCESSING = "processing"
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    DELETED = "deleted"


class JobStatus(str, Enum):
    """持久化后台任务状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobOperation(str, Enum):
    """知识库后台任务类型。"""

    INDEX = "index"
    REINDEX = "reindex"
    ROLLBACK = "rollback"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """一个逻辑文档的当前管理状态。"""

    document_id: str
    knowledge_base_id: str
    source_path: str
    filename: str
    media_type: str
    size_bytes: int
    status: DocumentStatus
    active_version_id: str | None
    active_vector_document_id: str | None
    chunk_count: int
    error_message: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class DocumentVersionRecord:
    """一个不可变的原始文件版本。"""

    version_id: str
    document_id: str
    content_hash: str
    storage_path: Path
    size_bytes: int
    status: VersionStatus
    vector_document_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class KnowledgeJobRecord:
    """一个可在进程重启后恢复的知识库任务。"""

    job_id: str
    document_id: str
    version_id: str | None
    operation: JobOperation
    status: JobStatus
    stage: str
    error_message: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ChunkEditRecord:
    """一次不保存正文的切片编辑审计记录。"""

    edit_id: str
    document_id: str
    vector_document_id: str
    chunk_index: int
    before_hash: str
    after_hash: str
    created_at: str


class KnowledgeCatalog:
    """通过短连接事务维护单知识库控制面状态。"""

    def __init__(self, path: Path, knowledge_base_id: str) -> None:
        """使用数据库路径和稳定知识库标识创建目录。"""
        self._path = path
        self._knowledge_base_id = knowledge_base_id

    async def initialize(self) -> None:
        """创建目录数据库及其约束和索引。"""
        await self._call(self._initialize_sync)

    async def list_documents(self) -> list[DocumentRecord]:
        """按最近更新时间倒序列出未删除文档。"""
        return await self._call(self._list_documents_sync)

    async def get_document(self, document_id: str) -> DocumentRecord:
        """根据稳定逻辑标识读取文档。"""
        return await self._call(self._get_document_sync, document_id)

    async def get_document_by_source(
        self,
        source_path: str,
    ) -> DocumentRecord | None:
        """根据受管目录相对路径读取文档。"""
        return await self._call(
            self._get_document_by_source_sync,
            source_path,
        )

    async def get_version(
        self,
        version_id: str,
    ) -> DocumentVersionRecord:
        """读取一个不可变原始文件版本。"""
        return await self._call(self._get_version_sync, version_id)

    async def list_versions(
        self,
        document_id: str,
    ) -> list[DocumentVersionRecord]:
        """按创建时间列出文档的全部内部版本。"""
        return await self._call(self._list_versions_sync, document_id)

    async def get_job(self, job_id: str) -> KnowledgeJobRecord:
        """读取一个后台任务。"""
        return await self._call(self._get_job_sync, job_id)

    async def latest_job_for_document(
        self,
        document_id: str,
    ) -> KnowledgeJobRecord | None:
        """读取文档最近创建的后台任务。"""
        return await self._call(
            self._latest_job_for_document_sync,
            document_id,
        )

    async def create_index_job(
        self,
        *,
        source_path: str,
        filename: str,
        media_type: str,
        size_bytes: int,
        content_hash: str,
        storage_path: Path,
        replace: bool,
    ) -> tuple[DocumentRecord, DocumentVersionRecord, KnowledgeJobRecord]:
        """登记上传版本并创建持久化索引任务。"""
        return await self._call(
            self._create_index_job_sync,
            source_path,
            filename,
            media_type,
            size_bytes,
            content_hash,
            storage_path,
            replace,
        )

    async def register_ready_document(
        self,
        *,
        source_path: str,
        filename: str,
        media_type: str,
        size_bytes: int,
        content_hash: str,
        storage_path: Path,
        vector_document_id: str,
        chunk_count: int,
    ) -> DocumentRecord:
        """把启动扫描发现的已有有效索引登记到目录。"""
        return await self._call(
            self._register_ready_document_sync,
            source_path,
            filename,
            media_type,
            size_bytes,
            content_hash,
            storage_path,
            vector_document_id,
            chunk_count,
        )

    async def register_unsupported_document(
        self,
        *,
        source_path: str,
        filename: str,
        size_bytes: int,
    ) -> DocumentRecord:
        """登记受管目录中无法解析的文件。"""
        return await self._call(
            self._register_unsupported_document_sync,
            source_path,
            filename,
            size_bytes,
        )

    async def create_reindex_job(
        self,
        document_id: str,
    ) -> KnowledgeJobRecord:
        """为当前活动版本创建重新索引任务。"""
        return await self._call(
            self._create_reindex_job_sync,
            document_id,
        )

    async def create_delete_job(
        self,
        document_id: str,
    ) -> KnowledgeJobRecord:
        """创建删除原文件、索引和媒体资产的任务。"""
        return await self._call(
            self._create_delete_job_sync,
            document_id,
        )

    async def create_rollback_job(
        self,
        document_id: str,
        version_id: str,
    ) -> KnowledgeJobRecord:
        """创建把历史原文件版本重新索引为活动版本的任务。"""
        return await self._call(
            self._create_rollback_job_sync,
            document_id,
            version_id,
        )

    async def record_chunk_edit(
        self,
        *,
        edit_id: str,
        document_id: str,
        vector_document_id: str,
        chunk_index: int,
        before_hash: str,
        after_hash: str,
    ) -> ChunkEditRecord:
        """记录一次已成功写入向量库的切片修改。"""
        return await self._call(
            self._record_chunk_edit_sync,
            edit_id,
            document_id,
            vector_document_id,
            chunk_index,
            before_hash,
            after_hash,
        )

    async def recover_interrupted_jobs(self) -> list[KnowledgeJobRecord]:
        """把进程中断时运行中的任务恢复为排队状态。"""
        return await self._call(self._recover_interrupted_jobs_sync)

    async def queued_jobs(self) -> list[KnowledgeJobRecord]:
        """按创建顺序返回所有待执行任务。"""
        return await self._call(self._queued_jobs_sync)

    async def mark_job_running(self, job_id: str, stage: str) -> None:
        """把任务和对应文档更新为处理中。"""
        await self._call(self._mark_job_running_sync, job_id, stage)

    async def update_job_stage(self, job_id: str, stage: str) -> None:
        """持久化任务当前公开阶段。"""
        await self._call(self._update_job_stage_sync, job_id, stage)

    async def complete_index_job(
        self,
        job_id: str,
        *,
        vector_document_id: str,
        chunk_count: int,
    ) -> None:
        """原子切换活动版本并完成索引任务。"""
        await self._call(
            self._complete_index_job_sync,
            job_id,
            vector_document_id,
            chunk_count,
        )

    async def complete_delete_job(self, job_id: str) -> None:
        """把文档及其全部版本标记为已删除。"""
        await self._call(self._complete_delete_job_sync, job_id)

    async def fail_job(self, job_id: str, message: str) -> None:
        """记录公开错误，并保留此前活动索引信息。"""
        await self._call(self._fail_job_sync, job_id, message)

    async def _call(
        self,
        operation: Callable[..., _T],
        *args: object,
    ) -> _T:
        """在线程中执行短生命周期 SQLite 操作。"""
        return await asyncio.to_thread(operation, *args)

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._migrate_document_scope_sync(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    active_version_id TEXT,
                    active_vector_document_id TEXT,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(knowledge_base_id, source_path)
                );
                CREATE TABLE IF NOT EXISTS knowledge_document_versions (
                    version_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    vector_document_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id)
                        REFERENCES knowledge_documents(document_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_jobs (
                    job_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    version_id TEXT,
                    operation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(document_id)
                        REFERENCES knowledge_documents(document_id),
                    FOREIGN KEY(version_id)
                        REFERENCES knowledge_document_versions(version_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_chunk_edits (
                    edit_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    vector_document_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    before_hash TEXT NOT NULL,
                    after_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id)
                        REFERENCES knowledge_documents(document_id)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_documents_scope
                    ON knowledge_documents(knowledge_base_id, status);
                CREATE INDEX IF NOT EXISTS idx_knowledge_versions_document
                    ON knowledge_document_versions(document_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_status
                    ON knowledge_jobs(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_edits_document
                    ON knowledge_chunk_edits(document_id, created_at);
                """,
            )

    @staticmethod
    def _migrate_document_scope_sync(
        connection: sqlite3.Connection,
    ) -> None:
        """把旧版全局文件名唯一约束迁移为知识库内唯一。"""
        table = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'knowledge_documents'
            """,
        ).fetchone()
        if table is None:
            return
        indexes = connection.execute(
            "PRAGMA index_list('knowledge_documents')",
        ).fetchall()
        has_legacy_unique = False
        for index in indexes:
            if not bool(index["unique"]):
                continue
            columns = connection.execute(
                f"PRAGMA index_info('{index['name']}')",
            ).fetchall()
            if [column["name"] for column in columns] == ["source_path"]:
                has_legacy_unique = True
                break
        if not has_legacy_unique:
            return

        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            CREATE TABLE knowledge_documents_scoped (
                document_id TEXT PRIMARY KEY,
                knowledge_base_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                media_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                status TEXT NOT NULL,
                active_version_id TEXT,
                active_vector_document_id TEXT,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(knowledge_base_id, source_path)
            );
            INSERT INTO knowledge_documents_scoped
            SELECT * FROM knowledge_documents;
            DROP TABLE knowledge_documents;
            ALTER TABLE knowledge_documents_scoped
                RENAME TO knowledge_documents;
            """,
        )
        connection.execute("PRAGMA foreign_keys = ON")

    def _list_documents_sync(self) -> list[DocumentRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM knowledge_documents
                WHERE knowledge_base_id = ? AND status != ?
                ORDER BY updated_at DESC, filename ASC
                """,
                (self._knowledge_base_id, DocumentStatus.DELETED.value),
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def _get_document_sync(self, document_id: str) -> DocumentRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_documents
                WHERE document_id = ? AND knowledge_base_id = ?
                """,
                (document_id, self._knowledge_base_id),
            ).fetchone()
        if row is None:
            raise CatalogNotFoundError("文档不存在。")
        return _document_from_row(row)

    def _get_document_by_source_sync(
        self,
        source_path: str,
    ) -> DocumentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_documents
                WHERE source_path = ? AND knowledge_base_id = ?
                """,
                (source_path, self._knowledge_base_id),
            ).fetchone()
        return None if row is None else _document_from_row(row)

    def _get_version_sync(
        self,
        version_id: str,
    ) -> DocumentVersionRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT versions.*
                FROM knowledge_document_versions AS versions
                JOIN knowledge_documents AS documents
                    ON documents.document_id = versions.document_id
                WHERE versions.version_id = ?
                    AND documents.knowledge_base_id = ?
                """,
                (version_id, self._knowledge_base_id),
            ).fetchone()
        if row is None:
            raise CatalogNotFoundError("文档版本不存在。")
        return _version_from_row(row)

    def _list_versions_sync(
        self,
        document_id: str,
    ) -> list[DocumentVersionRecord]:
        self._get_document_sync(document_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM knowledge_document_versions
                WHERE document_id = ? ORDER BY created_at ASC
                """,
                (document_id,),
            ).fetchall()
        return [_version_from_row(row) for row in rows]

    def _get_job_sync(self, job_id: str) -> KnowledgeJobRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT jobs.*
                FROM knowledge_jobs AS jobs
                JOIN knowledge_documents AS documents
                    ON documents.document_id = jobs.document_id
                WHERE jobs.job_id = ?
                    AND documents.knowledge_base_id = ?
                """,
                (job_id, self._knowledge_base_id),
            ).fetchone()
        if row is None:
            raise CatalogNotFoundError("后台任务不存在。")
        return _job_from_row(row)

    def _latest_job_for_document_sync(
        self,
        document_id: str,
    ) -> KnowledgeJobRecord | None:
        self._get_document_sync(document_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_jobs
                WHERE document_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (document_id,),
            ).fetchone()
        return None if row is None else _job_from_row(row)

    def _create_index_job_sync(
        self,
        source_path: str,
        filename: str,
        media_type: str,
        size_bytes: int,
        content_hash: str,
        storage_path: Path,
        replace: bool,
    ) -> tuple[DocumentRecord, DocumentVersionRecord, KnowledgeJobRecord]:
        now = _now()
        version_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_documents
                WHERE source_path = ? AND knowledge_base_id = ?
                """,
                (source_path, self._knowledge_base_id),
            ).fetchone()
            if row is not None and row["status"] != DocumentStatus.DELETED.value:
                if not replace:
                    raise CatalogConflictError(
                        "同名文档已经存在，请明确选择替换。",
                    )
                document_id = cast(str, row["document_id"])
                connection.execute(
                    """
                    UPDATE knowledge_documents
                    SET filename = ?, media_type = ?, size_bytes = ?,
                        status = ?, error_message = NULL, updated_at = ?
                    WHERE document_id = ?
                    """,
                    (
                        filename,
                        media_type,
                        size_bytes,
                        DocumentStatus.QUEUED.value,
                        now,
                        document_id,
                    ),
                )
            else:
                document_id = uuid.uuid4().hex
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO knowledge_documents (
                            document_id, knowledge_base_id, source_path,
                            filename, media_type, size_bytes, status,
                            chunk_count, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                        """,
                        (
                            document_id,
                            self._knowledge_base_id,
                            source_path,
                            filename,
                            media_type,
                            size_bytes,
                            DocumentStatus.QUEUED.value,
                            now,
                            now,
                        ),
                    )
                else:
                    document_id = cast(str, row["document_id"])
                    connection.execute(
                        """
                        UPDATE knowledge_documents
                        SET filename = ?, media_type = ?, size_bytes = ?,
                            status = ?, active_version_id = NULL,
                            active_vector_document_id = NULL,
                            chunk_count = 0, error_message = NULL,
                            updated_at = ?
                        WHERE document_id = ?
                        """,
                        (
                            filename,
                            media_type,
                            size_bytes,
                            DocumentStatus.QUEUED.value,
                            now,
                            document_id,
                        ),
                    )

            connection.execute(
                """
                INSERT INTO knowledge_document_versions (
                    version_id, document_id, content_hash, storage_path,
                    size_bytes, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    document_id,
                    content_hash,
                    str(storage_path),
                    size_bytes,
                    VersionStatus.QUEUED.value,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO knowledge_jobs (
                    job_id, document_id, version_id, operation, status,
                    stage, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    document_id,
                    version_id,
                    JobOperation.INDEX.value,
                    JobStatus.QUEUED.value,
                    "等待处理",
                    now,
                    now,
                ),
            )
            connection.commit()
            document_row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            version_row = connection.execute(
                """
                SELECT * FROM knowledge_document_versions
                WHERE version_id = ?
                """,
                (version_id,),
            ).fetchone()
            job_row = connection.execute(
                "SELECT * FROM knowledge_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return (
            _document_from_required_row(document_row),
            _version_from_required_row(version_row),
            _job_from_required_row(job_row),
        )

    def _register_ready_document_sync(
        self,
        source_path: str,
        filename: str,
        media_type: str,
        size_bytes: int,
        content_hash: str,
        storage_path: Path,
        vector_document_id: str,
        chunk_count: int,
    ) -> DocumentRecord:
        existing = self._get_document_by_source_sync(source_path)
        if (
            existing is not None
            and existing.status == DocumentStatus.READY
            and existing.active_vector_document_id == vector_document_id
        ):
            return existing
        document, version, job = self._create_index_job_sync(
            source_path,
            filename,
            media_type,
            size_bytes,
            content_hash,
            storage_path,
            existing is not None,
        )
        self._complete_index_job_sync(
            job.job_id,
            vector_document_id,
            chunk_count,
        )
        return self._get_document_sync(document.document_id)

    def _register_unsupported_document_sync(
        self,
        source_path: str,
        filename: str,
        size_bytes: int,
    ) -> DocumentRecord:
        now = _now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_documents
                WHERE source_path = ? AND knowledge_base_id = ?
                """,
                (source_path, self._knowledge_base_id),
            ).fetchone()
            if row is None:
                document_id = uuid.uuid4().hex
                connection.execute(
                    """
                    INSERT INTO knowledge_documents (
                        document_id, knowledge_base_id, source_path,
                        filename, media_type, size_bytes, status,
                        chunk_count, error_message, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        document_id,
                        self._knowledge_base_id,
                        source_path,
                        filename,
                        "application/octet-stream",
                        size_bytes,
                        DocumentStatus.UNSUPPORTED.value,
                        "当前版本不支持该文件格式。",
                        now,
                        now,
                    ),
                )
            else:
                document_id = cast(str, row["document_id"])
                connection.execute(
                    """
                    UPDATE knowledge_documents
                    SET size_bytes = ?, status = ?, error_message = ?,
                        updated_at = ?
                    WHERE document_id = ?
                    """,
                    (
                        size_bytes,
                        DocumentStatus.UNSUPPORTED.value,
                        "当前版本不支持该文件格式。",
                        now,
                        document_id,
                    ),
                )
            connection.commit()
        return self._get_document_sync(document_id)

    def _create_reindex_job_sync(
        self,
        document_id: str,
    ) -> KnowledgeJobRecord:
        document = self._get_document_sync(document_id)
        if document.active_version_id is None:
            raise CatalogError("文档没有可重新索引的活动版本。")
        return self._create_job_sync(
            document_id,
            document.active_version_id,
            JobOperation.REINDEX,
            DocumentStatus.QUEUED,
        )

    def _create_delete_job_sync(
        self,
        document_id: str,
    ) -> KnowledgeJobRecord:
        document = self._get_document_sync(document_id)
        if document.status == DocumentStatus.DELETED:
            raise CatalogNotFoundError("文档不存在。")
        return self._create_job_sync(
            document_id,
            None,
            JobOperation.DELETE,
            DocumentStatus.DELETING,
        )

    def _create_rollback_job_sync(
        self,
        document_id: str,
        version_id: str,
    ) -> KnowledgeJobRecord:
        document = self._get_document_sync(document_id)
        version = self._get_version_sync(version_id)
        if version.document_id != document.document_id:
            raise CatalogNotFoundError("文档版本不属于当前文档。")
        if version.status not in {
            VersionStatus.ACTIVE,
            VersionStatus.INACTIVE,
        }:
            raise CatalogConflictError("该文档版本当前不可回滚。")
        if version.version_id == document.active_version_id:
            raise CatalogConflictError("该文档版本已经处于活动状态。")
        return self._create_job_sync(
            document_id,
            version_id,
            JobOperation.ROLLBACK,
            DocumentStatus.QUEUED,
        )

    def _record_chunk_edit_sync(
        self,
        edit_id: str,
        document_id: str,
        vector_document_id: str,
        chunk_index: int,
        before_hash: str,
        after_hash: str,
    ) -> ChunkEditRecord:
        document = self._get_document_sync(document_id)
        if document.active_vector_document_id != vector_document_id:
            raise CatalogConflictError("文档索引已变化，请刷新切片后重试。")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_chunk_edits (
                    edit_id, document_id, vector_document_id, chunk_index,
                    before_hash, after_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edit_id,
                    document_id,
                    vector_document_id,
                    chunk_index,
                    before_hash,
                    after_hash,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE knowledge_documents SET updated_at = ?
                WHERE document_id = ?
                """,
                (now, document_id),
            )
            connection.commit()
        return ChunkEditRecord(
            edit_id=edit_id,
            document_id=document_id,
            vector_document_id=vector_document_id,
            chunk_index=chunk_index,
            before_hash=before_hash,
            after_hash=after_hash,
            created_at=now,
        )

    def _create_job_sync(
        self,
        document_id: str,
        version_id: str | None,
        operation: JobOperation,
        document_status: DocumentStatus,
    ) -> KnowledgeJobRecord:
        now = _now()
        job_id = uuid.uuid4().hex
        with self._connect() as connection:
            pending = connection.execute(
                """
                SELECT 1 FROM knowledge_jobs
                WHERE document_id = ? AND status IN (?, ?)
                LIMIT 1
                """,
                (
                    document_id,
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                ),
            ).fetchone()
            if pending is not None:
                raise CatalogConflictError("文档已有任务正在处理。")
            connection.execute(
                """
                UPDATE knowledge_documents
                SET status = ?, error_message = NULL, updated_at = ?
                WHERE document_id = ?
                """,
                (document_status.value, now, document_id),
            )
            connection.execute(
                """
                INSERT INTO knowledge_jobs (
                    job_id, document_id, version_id, operation, status,
                    stage, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    document_id,
                    version_id,
                    operation.value,
                    JobStatus.QUEUED.value,
                    "等待处理",
                    now,
                    now,
                ),
            )
            connection.commit()
        return self._get_job_sync(job_id)

    def _recover_interrupted_jobs_sync(self) -> list[KnowledgeJobRecord]:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE knowledge_jobs
                SET status = ?, stage = ?, updated_at = ?
                WHERE status = ? AND document_id IN (
                    SELECT document_id FROM knowledge_documents
                    WHERE knowledge_base_id = ?
                )
                """,
                (
                    JobStatus.QUEUED.value,
                    "等待恢复",
                    now,
                    JobStatus.RUNNING.value,
                    self._knowledge_base_id,
                ),
            )
            connection.execute(
                """
                UPDATE knowledge_documents
                SET status = ?, updated_at = ?
                WHERE document_id IN (
                    SELECT document_id FROM knowledge_jobs
                    WHERE status = ? AND operation != ?
                )
                AND knowledge_base_id = ?
                """,
                (
                    DocumentStatus.QUEUED.value,
                    now,
                    JobStatus.QUEUED.value,
                    JobOperation.DELETE.value,
                    self._knowledge_base_id,
                ),
            )
            connection.commit()
        return self._queued_jobs_sync()

    def _queued_jobs_sync(self) -> list[KnowledgeJobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT jobs.*
                FROM knowledge_jobs AS jobs
                JOIN knowledge_documents AS documents
                    ON documents.document_id = jobs.document_id
                WHERE jobs.status = ?
                    AND documents.knowledge_base_id = ?
                ORDER BY jobs.created_at ASC
                """,
                (JobStatus.QUEUED.value, self._knowledge_base_id),
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def _mark_job_running_sync(self, job_id: str, stage: str) -> None:
        job = self._get_job_sync(job_id)
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE knowledge_jobs
                SET status = ?, stage = ?, error_message = NULL,
                    updated_at = ? WHERE job_id = ?
                """,
                (JobStatus.RUNNING.value, stage, now, job_id),
            )
            connection.execute(
                """
                UPDATE knowledge_documents
                SET status = ?, error_message = NULL, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    DocumentStatus.DELETING.value
                    if job.operation == JobOperation.DELETE
                    else DocumentStatus.PROCESSING.value,
                    now,
                    job.document_id,
                ),
            )
            if (
                job.version_id is not None
                and job.operation == JobOperation.INDEX
            ):
                connection.execute(
                    """
                    UPDATE knowledge_document_versions
                    SET status = ? WHERE version_id = ?
                    """,
                    (VersionStatus.PROCESSING.value, job.version_id),
                )
            connection.commit()

    def _update_job_stage_sync(self, job_id: str, stage: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE knowledge_jobs SET stage = ?, updated_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (stage, _now(), job_id, JobStatus.RUNNING.value),
            )
            if cursor.rowcount == 0:
                raise CatalogNotFoundError("运行中的后台任务不存在。")
            connection.commit()

    def _complete_index_job_sync(
        self,
        job_id: str,
        vector_document_id: str,
        chunk_count: int,
    ) -> None:
        job = self._get_job_sync(job_id)
        if job.version_id is None:
            raise CatalogError("索引任务缺少文档版本。")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE knowledge_document_versions
                SET status = ?
                WHERE document_id = ? AND status = ?
                """,
                (
                    VersionStatus.INACTIVE.value,
                    job.document_id,
                    VersionStatus.ACTIVE.value,
                ),
            )
            connection.execute(
                """
                UPDATE knowledge_document_versions
                SET status = ?, vector_document_id = ?
                WHERE version_id = ?
                """,
                (
                    VersionStatus.ACTIVE.value,
                    vector_document_id,
                    job.version_id,
                ),
            )
            connection.execute(
                """
                UPDATE knowledge_documents
                SET status = ?, active_version_id = ?,
                    active_vector_document_id = ?, chunk_count = ?,
                    error_message = NULL, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    DocumentStatus.READY.value,
                    job.version_id,
                    vector_document_id,
                    chunk_count,
                    now,
                    job.document_id,
                ),
            )
            connection.execute(
                """
                UPDATE knowledge_jobs
                SET status = ?, stage = ?, error_message = NULL,
                    updated_at = ? WHERE job_id = ?
                """,
                (
                    JobStatus.SUCCEEDED.value,
                    "处理完成",
                    now,
                    job_id,
                ),
            )
            connection.commit()

    def _complete_delete_job_sync(self, job_id: str) -> None:
        job = self._get_job_sync(job_id)
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE knowledge_document_versions SET status = ?
                WHERE document_id = ?
                """,
                (VersionStatus.DELETED.value, job.document_id),
            )
            connection.execute(
                """
                UPDATE knowledge_documents
                SET status = ?, active_version_id = NULL,
                    active_vector_document_id = NULL, chunk_count = 0,
                    error_message = NULL, updated_at = ?
                WHERE document_id = ?
                """,
                (DocumentStatus.DELETED.value, now, job.document_id),
            )
            connection.execute(
                """
                UPDATE knowledge_jobs
                SET status = ?, stage = ?, error_message = NULL,
                    updated_at = ? WHERE job_id = ?
                """,
                (
                    JobStatus.SUCCEEDED.value,
                    "删除完成",
                    now,
                    job_id,
                ),
            )
            connection.commit()

    def _fail_job_sync(self, job_id: str, message: str) -> None:
        job = self._get_job_sync(job_id)
        public_message = message[:1000]
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE knowledge_jobs
                SET status = ?, stage = ?, error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    JobStatus.FAILED.value,
                    "处理失败",
                    public_message,
                    now,
                    job_id,
                ),
            )
            connection.execute(
                """
                UPDATE knowledge_documents
                SET status = ?, error_message = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    DocumentStatus.FAILED.value,
                    public_message,
                    now,
                    job.document_id,
                ),
            )
            if (
                job.version_id is not None
                and job.operation == JobOperation.INDEX
            ):
                connection.execute(
                    """
                    UPDATE knowledge_document_versions
                    SET status = ? WHERE version_id = ?
                    """,
                    (VersionStatus.FAILED.value, job.version_id),
                )
            connection.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """创建、配置并确保关闭一个短生命周期连接。"""
        connection = sqlite3.connect(self._path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
        finally:
            connection.close()


def _document_from_required_row(row: sqlite3.Row | None) -> DocumentRecord:
    if row is None:
        raise CatalogError("文档目录写入后无法读取。")
    return _document_from_row(row)


def _version_from_required_row(
    row: sqlite3.Row | None,
) -> DocumentVersionRecord:
    if row is None:
        raise CatalogError("文档版本写入后无法读取。")
    return _version_from_row(row)


def _job_from_required_row(row: sqlite3.Row | None) -> KnowledgeJobRecord:
    if row is None:
        raise CatalogError("后台任务写入后无法读取。")
    return _job_from_row(row)


def _document_from_row(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        document_id=cast(str, row["document_id"]),
        knowledge_base_id=cast(str, row["knowledge_base_id"]),
        source_path=cast(str, row["source_path"]),
        filename=cast(str, row["filename"]),
        media_type=cast(str, row["media_type"]),
        size_bytes=cast(int, row["size_bytes"]),
        status=DocumentStatus(cast(str, row["status"])),
        active_version_id=cast(str | None, row["active_version_id"]),
        active_vector_document_id=cast(
            str | None,
            row["active_vector_document_id"],
        ),
        chunk_count=cast(int, row["chunk_count"]),
        error_message=cast(str | None, row["error_message"]),
        created_at=cast(str, row["created_at"]),
        updated_at=cast(str, row["updated_at"]),
    )


def _version_from_row(row: sqlite3.Row) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        version_id=cast(str, row["version_id"]),
        document_id=cast(str, row["document_id"]),
        content_hash=cast(str, row["content_hash"]),
        storage_path=Path(cast(str, row["storage_path"])),
        size_bytes=cast(int, row["size_bytes"]),
        status=VersionStatus(cast(str, row["status"])),
        vector_document_id=cast(str | None, row["vector_document_id"]),
        created_at=cast(str, row["created_at"]),
    )


def _job_from_row(row: sqlite3.Row) -> KnowledgeJobRecord:
    return KnowledgeJobRecord(
        job_id=cast(str, row["job_id"]),
        document_id=cast(str, row["document_id"]),
        version_id=cast(str | None, row["version_id"]),
        operation=JobOperation(cast(str, row["operation"])),
        status=JobStatus(cast(str, row["status"])),
        stage=cast(str, row["stage"]),
        error_message=cast(str | None, row["error_message"]),
        created_at=cast(str, row["created_at"]),
        updated_at=cast(str, row["updated_at"]),
    )


def _now() -> str:
    """返回可按字符串排序的 UTC 时间。"""
    return datetime.now(UTC).isoformat()

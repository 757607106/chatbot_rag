"""知识库持久化目录测试。"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from chatbot_rag.rag import (
    CatalogConflictError,
    DocumentStatus,
    JobOperation,
    JobStatus,
    KnowledgeCatalog,
)


@pytest.mark.asyncio
async def test_catalog_persists_index_lifecycle_and_rejects_implicit_replace(
    tmp_path: Path,
) -> None:
    """目录应持久化版本和任务，并拒绝未确认的同名替换。"""
    catalog = KnowledgeCatalog(tmp_path / "catalog.sqlite3", "knowledge")
    await catalog.initialize()
    version_path = tmp_path / "version.md"
    version_path.write_text("知识内容", encoding="utf-8")

    document, version, job = await catalog.create_index_job(
        source_path="guide.md",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=12,
        content_hash="hash-v1",
        storage_path=version_path,
        replace=False,
    )

    assert document.status == DocumentStatus.QUEUED
    assert version.document_id == document.document_id
    assert job.status == JobStatus.QUEUED

    with pytest.raises(CatalogConflictError, match="明确选择替换"):
        await catalog.create_index_job(
            source_path="guide.md",
            filename="guide.md",
            media_type="text/markdown",
            size_bytes=12,
            content_hash="hash-v2",
            storage_path=tmp_path / "version-2.md",
            replace=False,
        )

    await catalog.mark_job_running(job.job_id, "正在创建索引")
    await catalog.complete_index_job(
        job.job_id,
        vector_document_id="vector-v1",
        chunk_count=3,
    )

    ready = await catalog.get_document(document.document_id)
    assert ready.status == DocumentStatus.READY
    assert ready.active_version_id == version.version_id
    assert ready.active_vector_document_id == "vector-v1"
    assert ready.chunk_count == 3


@pytest.mark.asyncio
async def test_catalog_recovers_interrupted_reindex_without_losing_active_version(
    tmp_path: Path,
) -> None:
    """重建任务中断或失败时应保留此前活动版本。"""
    catalog = KnowledgeCatalog(tmp_path / "catalog.sqlite3", "knowledge")
    await catalog.initialize()
    document, version, first_job = await catalog.create_index_job(
        source_path="guide.md",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=8,
        content_hash="hash",
        storage_path=tmp_path / "version.md",
        replace=False,
    )
    await catalog.mark_job_running(first_job.job_id, "索引中")
    await catalog.complete_index_job(
        first_job.job_id,
        vector_document_id="vector-v1",
        chunk_count=2,
    )

    reindex_job = await catalog.create_reindex_job(document.document_id)
    await catalog.mark_job_running(reindex_job.job_id, "重建中")
    recovered = await catalog.recover_interrupted_jobs()

    assert [job.job_id for job in recovered] == [reindex_job.job_id]
    assert recovered[0].status == JobStatus.QUEUED

    await catalog.mark_job_running(reindex_job.job_id, "重建中")
    await catalog.fail_job(reindex_job.job_id, "重建失败")

    failed = await catalog.get_document(document.document_id)
    active_version = await catalog.get_version(version.version_id)
    assert failed.status == DocumentStatus.FAILED
    assert failed.active_vector_document_id == "vector-v1"
    assert active_version.status.value == "active"


@pytest.mark.asyncio
async def test_catalog_scopes_same_source_to_each_knowledge_base(
    tmp_path: Path,
) -> None:
    """不同知识库应允许使用相同文件名且不能交叉读取。"""
    path = tmp_path / "catalog.sqlite3"
    first = KnowledgeCatalog(path, "kb-first")
    second = KnowledgeCatalog(path, "kb-second")
    await first.initialize()
    await second.initialize()

    first_document, _, _ = await first.create_index_job(
        source_path="guide.md",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=1,
        content_hash="first",
        storage_path=tmp_path / "first.md",
        replace=False,
    )
    second_document, _, _ = await second.create_index_job(
        source_path="guide.md",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=1,
        content_hash="second",
        storage_path=tmp_path / "second.md",
        replace=False,
    )

    assert first_document.document_id != second_document.document_id
    assert (await first.list_documents()) == [first_document]
    assert (await second.list_documents()) == [second_document]


@pytest.mark.asyncio
async def test_catalog_rolls_back_to_inactive_original_version(
    tmp_path: Path,
) -> None:
    """回滚任务应重新激活历史版本并保留完整版本历史。"""
    catalog = KnowledgeCatalog(tmp_path / "catalog.sqlite3", "knowledge")
    await catalog.initialize()
    document, version_one, first_job = await catalog.create_index_job(
        source_path="guide.md",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=2,
        content_hash="v1",
        storage_path=tmp_path / "v1.md",
        replace=False,
    )
    await catalog.mark_job_running(first_job.job_id, "索引")
    await catalog.complete_index_job(
        first_job.job_id,
        vector_document_id="vector-v1",
        chunk_count=1,
    )
    _, version_two, second_job = await catalog.create_index_job(
        source_path="guide.md",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=2,
        content_hash="v2",
        storage_path=tmp_path / "v2.md",
        replace=True,
    )
    await catalog.mark_job_running(second_job.job_id, "索引")
    await catalog.complete_index_job(
        second_job.job_id,
        vector_document_id="vector-v2",
        chunk_count=2,
    )

    rollback = await catalog.create_rollback_job(
        document.document_id,
        version_one.version_id,
    )
    assert rollback.operation == JobOperation.ROLLBACK
    await catalog.mark_job_running(rollback.job_id, "回滚")
    await catalog.complete_index_job(
        rollback.job_id,
        vector_document_id="vector-rollback",
        chunk_count=1,
    )

    current = await catalog.get_document(document.document_id)
    assert current.active_version_id == version_one.version_id
    assert current.active_vector_document_id == "vector-rollback"
    inactive = await catalog.get_version(version_two.version_id)
    assert inactive.status.value == "inactive"


@pytest.mark.asyncio
async def test_catalog_migrates_legacy_global_source_uniqueness(
    tmp_path: Path,
) -> None:
    """旧数据库应自动迁移为知识库内文件名唯一。"""
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE knowledge_documents (
                document_id TEXT PRIMARY KEY,
                knowledge_base_id TEXT NOT NULL,
                source_path TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                media_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                status TEXT NOT NULL,
                active_version_id TEXT,
                active_vector_document_id TEXT,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )
        connection.executescript(
            """
            CREATE TABLE knowledge_document_versions (
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
            CREATE TABLE knowledge_jobs (
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
            """,
        )
        connection.commit()

    first = KnowledgeCatalog(path, "first")
    second = KnowledgeCatalog(path, "second")
    await first.initialize()
    await second.initialize()
    await first.register_unsupported_document(
        source_path="legacy.doc",
        filename="legacy.doc",
        size_bytes=1,
    )
    await second.register_unsupported_document(
        source_path="legacy.doc",
        filename="legacy.doc",
        size_bytes=1,
    )

    assert len(await first.list_documents()) == 1
    assert len(await second.list_documents()) == 1
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

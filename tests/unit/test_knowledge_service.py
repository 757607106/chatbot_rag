"""知识库异步管理服务测试。"""

from pathlib import Path
from typing import cast

import pytest
from agentscope.message import TextBlock
from agentscope.rag import Chunk, KnowledgeBase

from chatbot_rag.rag import (
    ChunkEditResult,
    ChunkPage,
    DocumentIngestor,
    DocumentStatus,
    IndexedDocument,
    IngestionStage,
    KnowledgeCatalog,
    MediaAssetStore,
    QdrantChunkReader,
    content_hash,
)
from chatbot_rag.services import (
    InvalidDocumentUploadError,
    KnowledgeManagementService,
)


class FakeKnowledgeBase:
    """仅提供启动对账所需的空知识库。"""

    name = "project_knowledge"

    async def list_documents(self) -> list[object]:
        """返回空的既有索引摘要。"""
        return []


class FakeIngestor:
    """记录索引和删除调用的单文档摄取器。"""

    def __init__(self) -> None:
        """初始化调用记录。"""
        self.indexed: list[str] = []
        self.deleted: list[str] = []

    async def ingest_file(
        self,
        file_path: Path,
        source_path: str,
        vector_document_id: str,
        document_metadata: object,
        progress_callback: object,
        media_document_key: str | None = None,
    ) -> IndexedDocument:
        """返回确定性的索引结果。"""
        del document_metadata, media_document_key
        if callable(progress_callback):
            progress_callback(IngestionStage.PARSING)
            progress_callback(IngestionStage.INDEXING)
        self.indexed.append(source_path)
        return IndexedDocument(
            vector_document_id=vector_document_id,
            content_hash="hash",
            chunk_count=4,
        )

    async def delete_source(
        self,
        source_path: str,
        media_document_key: str | None = None,
    ) -> int:
        """记录来源删除。"""
        del media_document_key
        self.deleted.append(source_path)
        return 1


class FakeChunkReader:
    """返回确定性真实切片页的读取器替身。"""

    async def list_chunks(
        self,
        vector_document_id: str,
        *,
        offset: int,
        limit: int,
    ) -> ChunkPage:
        """验证活动向量标识并返回一个文本切片。"""
        assert vector_document_id
        return ChunkPage(
            items=(
                Chunk(
                    content=TextBlock(type="text", text="索引切片内容"),
                    source="guide.md",
                    chunk_index=0,
                    total_chunks=1,
                    metadata={"heading": "说明"},
                ),
            ),
            total=1,
            offset=offset,
            limit=limit,
        )

    async def update_text_chunk(
        self,
        vector_document_id: str,
        chunk_index: int,
        *,
        content: str,
        expected_content_hash: str,
    ) -> ChunkEditResult:
        """返回包含手工编辑标记的确定性切片。"""
        assert vector_document_id
        assert chunk_index == 0
        assert expected_content_hash == content_hash("索引切片内容")
        chunk = Chunk(
            content=TextBlock(type="text", text=content),
            source="guide.md",
            chunk_index=0,
            total_chunks=1,
            metadata={"manual_edit_id": "edit-id"},
        )
        return ChunkEditResult(
            edit_id="edit-id",
            chunk=chunk,
            before_hash=expected_content_hash,
            after_hash=content_hash(content),
            edited_at="2026-01-01T00:00:00+00:00",
        )


@pytest.mark.asyncio
async def test_service_processes_upload_and_delete_with_persistent_status(
    tmp_path: Path,
) -> None:
    """上传和删除任务应异步收敛目录、原文件与状态。"""
    documents_path = tmp_path / "documents"
    ingestor = FakeIngestor()
    service = KnowledgeManagementService(
        knowledge_base=cast(KnowledgeBase, FakeKnowledgeBase()),
        ingestor=cast(DocumentIngestor, ingestor),
        catalog=KnowledgeCatalog(tmp_path / "catalog.sqlite3", "project_knowledge"),
        chunk_reader=cast(QdrantChunkReader, FakeChunkReader()),
        media_store=MediaAssetStore(tmp_path / "media", ()),
        knowledge_base_id="project_knowledge",
        knowledge_base_name="project_knowledge",
        media_document_prefix=None,
        documents_path=documents_path,
        versions_path=tmp_path / "versions",
        max_upload_bytes=1024,
    )
    await service.start()
    try:
        document, job = await service.upload_document(
            filename="guide.md",
            media_type="text/markdown",
            content=b"knowledge",
            replace=False,
        )
        assert job.status.value == "queued"

        await service.wait_for_idle()

        managed = await service.get_document(document.document_id)
        assert managed.document.status == DocumentStatus.READY
        assert managed.document.chunk_count == 4
        assert (documents_path / "guide.md").read_bytes() == b"knowledge"
        assert ingestor.indexed == ["guide.md"]

        chunks = await service.list_chunks(
            document.document_id,
            offset=0,
            limit=10,
        )
        assert chunks.total == 1
        assert chunks.items[0].content == "索引切片内容"
        assert chunks.items[0].metadata == {"heading": "说明"}

        await service.delete_document(document.document_id)
        await service.wait_for_idle()

        assert await service.list_documents() == []
        assert not (documents_path / "guide.md").exists()
        assert ingestor.deleted == ["guide.md"]
    finally:
        await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("../guide.md", b"value", "文件名无效"),
        ("legacy.doc", b"value", "不支持"),
        ("empty.md", b"", "不能为空"),
        ("large.md", b"too-large", "不能超过"),
    ],
)
async def test_service_rejects_unsafe_or_invalid_uploads(
    tmp_path: Path,
    filename: str,
    content: bytes,
    message: str,
) -> None:
    """服务边界应在写目录前拒绝危险名称、格式和大小。"""
    catalog = KnowledgeCatalog(
        tmp_path / "catalog.sqlite3",
        "project_knowledge",
    )
    service = KnowledgeManagementService(
        knowledge_base=cast(KnowledgeBase, FakeKnowledgeBase()),
        ingestor=cast(DocumentIngestor, FakeIngestor()),
        catalog=catalog,
        chunk_reader=cast(QdrantChunkReader, object()),
        media_store=MediaAssetStore(tmp_path / "media", ()),
        knowledge_base_id="project_knowledge",
        knowledge_base_name="project_knowledge",
        media_document_prefix=None,
        documents_path=tmp_path / "documents",
        versions_path=tmp_path / "versions",
        max_upload_bytes=5,
    )
    await catalog.initialize()

    with pytest.raises(InvalidDocumentUploadError, match=message):
        await service.upload_document(
            filename=filename,
            media_type=None,
            content=content,
            replace=False,
        )


@pytest.mark.asyncio
async def test_service_edits_chunk_and_rolls_back_original_version(
    tmp_path: Path,
) -> None:
    """切片编辑应记录哈希，版本回滚应恢复历史原文件。"""
    documents_path = tmp_path / "documents"
    service = KnowledgeManagementService(
        knowledge_base=cast(KnowledgeBase, FakeKnowledgeBase()),
        ingestor=cast(DocumentIngestor, FakeIngestor()),
        catalog=KnowledgeCatalog(
            tmp_path / "catalog.sqlite3",
            "project_knowledge",
        ),
        chunk_reader=cast(QdrantChunkReader, FakeChunkReader()),
        media_store=MediaAssetStore(tmp_path / "media", ()),
        knowledge_base_id="project_knowledge",
        knowledge_base_name="project_knowledge",
        media_document_prefix=None,
        documents_path=documents_path,
        versions_path=tmp_path / "versions",
        max_upload_bytes=1024,
    )
    await service.start()
    try:
        document, _ = await service.upload_document(
            filename="guide.md",
            media_type="text/markdown",
            content=b"version-one",
            replace=False,
        )
        await service.wait_for_idle()
        first_version = (await service.list_versions(document.document_id))[0]

        await service.upload_document(
            filename="guide.md",
            media_type="text/markdown",
            content=b"version-two",
            replace=True,
        )
        await service.wait_for_idle()
        edited = await service.update_chunk(
            document.document_id,
            0,
            content="人工修订",
            expected_content_hash=content_hash("索引切片内容"),
        )

        assert edited.content == "人工修订"
        assert edited.is_manually_edited is True

        await service.rollback_document(
            document.document_id,
            first_version.version_id,
        )
        await service.wait_for_idle()

        assert (documents_path / "guide.md").read_bytes() == b"version-one"
        current = await service.get_document(document.document_id)
        assert current.document.active_version_id == first_version.version_id
    finally:
        await service.stop()

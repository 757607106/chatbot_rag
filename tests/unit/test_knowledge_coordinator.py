"""多知识库协调器测试。"""

from pathlib import Path
from typing import cast

import pytest
from agentscope.embedding import EmbeddingModelBase, EmbeddingResponse
from agentscope.rag import KnowledgeBase, QdrantStore

from chatbot_rag.config import Settings
from chatbot_rag.rag import (
    KnowledgeBaseRuntimeFactory,
    KnowledgeBaseRegistry,
    MediaAssetStore,
)
from chatbot_rag.services import KnowledgeManagementCoordinator


class FakeEmbeddingModel:
    """为任意文本批次返回确定性二维向量。"""

    dimensions = 2
    supports_multimodal = False

    async def __call__(self, inputs: list[object]) -> EmbeddingResponse:
        """返回与输入数量一致的向量。"""
        return EmbeddingResponse(
            embeddings=[[0.1, 0.2] for _ in inputs],
        )


class FakeRuntimeFactory:
    """在共享 Qdrant 上按 collection 创建原生知识库。"""

    def __init__(self, store: QdrantStore) -> None:
        """保存共享向量存储。"""
        self._store = store
        self._embedding = cast(EmbeddingModelBase, FakeEmbeddingModel())

    def create(
        self,
        *,
        name: str,
        description: str,
        collection: str,
    ) -> KnowledgeBase:
        """创建隔离到指定 collection 的知识库。"""
        return KnowledgeBase(
            name=name,
            description=description,
            embedding_model=self._embedding,
            vector_store=self._store,
            collection=collection,
        )


@pytest.mark.asyncio
async def test_coordinator_creates_isolated_knowledge_base(
    tmp_path: Path,
) -> None:
    """不同知识库应允许同名文档且写入不同 collection。"""
    settings = Settings(
        dashscope_api_key="test-key",
        documents_path=tmp_path / "default-documents",
        knowledge_documents_root_path=tmp_path / "documents",
        document_versions_path=tmp_path / "versions",
        knowledge_catalog_path=tmp_path / "catalog.sqlite3",
        media_path=tmp_path / "media",
        qdrant_path=tmp_path / "qdrant",
        max_upload_bytes=1024,
    )
    store = QdrantStore(location=":memory:")
    async with store:
        coordinator = KnowledgeManagementCoordinator(
            settings=settings,
            registry=KnowledgeBaseRegistry(settings.knowledge_catalog_path),
            runtime_factory=cast(
                KnowledgeBaseRuntimeFactory,
                FakeRuntimeFactory(store),
            ),
            media_store=MediaAssetStore(settings.media_path, ()),
        )
        await coordinator.start()
        try:
            created = await coordinator.create_knowledge_base(
                name="产品资料",
                description="独立产品文档",
            )
            default_service = coordinator.default_service()
            created_service = coordinator.get_service(
                created.record.knowledge_base_id,
            )

            await default_service.upload_document(
                filename="guide.md",
                media_type="text/markdown",
                content=b"default content",
                replace=False,
            )
            await created_service.upload_document(
                filename="guide.md",
                media_type="text/markdown",
                content=b"secondary content",
                replace=False,
            )
            await default_service.wait_for_idle()
            await created_service.wait_for_idle()

            default_documents = await default_service.list_documents()
            created_documents = await created_service.list_documents()
            assert default_documents[0].document.source_path == "guide.md"
            assert created_documents[0].document.source_path == "guide.md"
            assert (
                default_documents[0].document.knowledge_base_id
                != created_documents[0].document.knowledge_base_id
            )
            assert created.record.documents_path.is_dir()
        finally:
            await coordinator.stop()

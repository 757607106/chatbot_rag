"""多知识库协调器测试。"""

from pathlib import Path
from typing import cast

import pytest
from agentscope.embedding import EmbeddingModelBase, EmbeddingResponse
from agentscope.rag import KnowledgeBase, QdrantStore

from chatbot_rag.config import Settings
from chatbot_rag.rag import (
    CatalogConflictError,
    CatalogNotFoundError,
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
        self.deleted_collections: list[str] = []

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

    async def delete_collection(self, collection: str) -> None:
        """记录被删除的物理 collection。"""
        self.deleted_collections.append(collection)


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


@pytest.mark.asyncio
async def test_coordinator_exposes_all_knowledge_bases_for_chat(
    tmp_path: Path,
) -> None:
    """聊天检索应拿到全部知识库句柄且默认知识库排在首位。"""
    settings = Settings(
        dashscope_api_key="test-key",
        documents_path=tmp_path / "default-documents",
        knowledge_documents_root_path=tmp_path / "documents",
        document_versions_path=tmp_path / "versions",
        knowledge_catalog_path=tmp_path / "catalog.sqlite3",
        media_path=tmp_path / "media",
        qdrant_path=tmp_path / "qdrant",
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

            knowledge_bases = await coordinator.chat_knowledge_bases()

            assert len(knowledge_bases) == 2
            assert knowledge_bases[0].name == settings.knowledge_base_name
            assert knowledge_bases[1].name == "产品资料"
            assert (
                knowledge_bases[1].description == created.record.description
            )
        finally:
            await coordinator.stop()


@pytest.mark.asyncio
async def test_coordinator_deletes_only_empty_non_default_knowledge_base(
    tmp_path: Path,
) -> None:
    """删除应拒绝默认库和有文档的库，空库则清理全部物理资源。"""
    settings = Settings(
        dashscope_api_key="test-key",
        documents_path=tmp_path / "default-documents",
        knowledge_documents_root_path=tmp_path / "documents",
        document_versions_path=tmp_path / "versions",
        knowledge_catalog_path=tmp_path / "catalog.sqlite3",
        media_path=tmp_path / "media",
        qdrant_path=tmp_path / "qdrant",
    )
    store = QdrantStore(location=":memory:")
    async with store:
        fake_factory = FakeRuntimeFactory(store)
        coordinator = KnowledgeManagementCoordinator(
            settings=settings,
            registry=KnowledgeBaseRegistry(settings.knowledge_catalog_path),
            runtime_factory=cast(KnowledgeBaseRuntimeFactory, fake_factory),
            media_store=MediaAssetStore(settings.media_path, ()),
        )
        await coordinator.start()
        try:
            created = await coordinator.create_knowledge_base(
                name="临时资料",
                description="待删除",
            )
            knowledge_base_id = created.record.knowledge_base_id
            service = coordinator.get_service(knowledge_base_id)

            with pytest.raises(CatalogConflictError):
                await coordinator.delete_knowledge_base(
                    settings.knowledge_base_name,
                )

            await service.upload_document(
                filename="guide.md",
                media_type="text/markdown",
                content=b"content",
                replace=False,
            )
            await service.wait_for_idle()
            with pytest.raises(CatalogConflictError):
                await coordinator.delete_knowledge_base(knowledge_base_id)

            documents = await service.list_documents()
            await service.delete_document(documents[0].document.document_id)
            await service.wait_for_idle()

            await coordinator.delete_knowledge_base(knowledge_base_id)

            assert fake_factory.deleted_collections == [
                created.record.collection_name,
            ]
            with pytest.raises(CatalogNotFoundError):
                await coordinator._registry.get_knowledge_base(
                    knowledge_base_id,
                )
            with pytest.raises(CatalogNotFoundError):
                coordinator.get_service(knowledge_base_id)
            assert not created.record.documents_path.exists()
            assert not (
                settings.document_versions_path / knowledge_base_id
            ).exists()
            remaining = await coordinator.chat_knowledge_bases()
            assert len(remaining) == 1
            assert remaining[0].name == settings.knowledge_base_name
        finally:
            await coordinator.stop()

"""Qdrant 真实切片读取测试。"""

from typing import cast

import pytest
from agentscope.embedding import EmbeddingModelBase, EmbeddingResponse
from agentscope.message import TextBlock
from agentscope.rag import (
    Chunk,
    KnowledgeBase,
    QdrantStore,
    VectorRecord,
)

from chatbot_rag.rag import (
    ChunkEditConflictError,
    ChunkReaderError,
    QdrantChunkReader,
    content_hash,
)


class ChunkKnowledgeBase:
    """向切片读取器暴露公开存储属性的知识库替身。"""

    def __init__(self, store: object) -> None:
        """保存待测试向量存储。"""
        self.vector_store = store
        self.collection = "knowledge"


class FakeEmbeddingModel:
    """为切片编辑返回确定性二维向量。"""

    dimensions = 2
    supports_multimodal = False

    async def __call__(self, inputs: object) -> EmbeddingResponse:
        """为唯一输入返回确定性向量。"""
        del inputs
        return EmbeddingResponse(embeddings=[[0.9, 0.1]])


@pytest.mark.asyncio
async def test_qdrant_chunk_reader_returns_index_payload_in_chunk_order() -> None:
    """切片浏览应读取 Qdrant payload 并按业务序号分页。"""
    store = QdrantStore(location=":memory:")
    async with store:
        await store.create_collection("knowledge", dimensions=2)
        await store.insert(
            "knowledge",
            [
                VectorRecord(
                    vector=[0.1, 0.2],
                    document_id="vector-document",
                    chunk=Chunk(
                        content=TextBlock(type="text", text="第二块"),
                        source="guide.md",
                        chunk_index=1,
                        total_chunks=2,
                    ),
                ),
                VectorRecord(
                    vector=[0.2, 0.3],
                    document_id="vector-document",
                    chunk=Chunk(
                        content=TextBlock(type="text", text="第一块"),
                        source="guide.md",
                        chunk_index=0,
                        total_chunks=2,
                    ),
                ),
            ],
        )
        reader = QdrantChunkReader(
            cast(KnowledgeBase, ChunkKnowledgeBase(store)),
        )

        page = await reader.list_chunks(
            "vector-document",
            offset=1,
            limit=1,
        )

    assert page.total == 2
    assert page.offset == 1
    assert page.items[0].chunk_index == 1
    assert isinstance(page.items[0].content, TextBlock)
    assert page.items[0].content.text == "第二块"


def test_qdrant_chunk_reader_rejects_other_vector_store() -> None:
    """非 Qdrant 存储不应伪造切片浏览能力。"""
    with pytest.raises(ChunkReaderError, match="不支持"):
        QdrantChunkReader(
            cast(KnowledgeBase, ChunkKnowledgeBase(object())),
        )


@pytest.mark.asyncio
async def test_qdrant_chunk_reader_validates_pagination() -> None:
    """无效分页参数应在访问 Qdrant 前被拒绝。"""
    store = QdrantStore(location=":memory:")
    reader = QdrantChunkReader(
        cast(KnowledgeBase, ChunkKnowledgeBase(store)),
    )

    with pytest.raises(ValueError, match="offset"):
        await reader.list_chunks("document", offset=-1)
    with pytest.raises(ValueError, match="limit"):
        await reader.list_chunks("document", limit=101)


@pytest.mark.asyncio
async def test_qdrant_chunk_reader_updates_one_chunk_with_hash_guard() -> None:
    """编辑切片应同时覆盖正文、向量和编辑元数据。"""
    store = QdrantStore(location=":memory:")
    async with store:
        knowledge_base = KnowledgeBase(
            name="knowledge",
            description="测试知识库",
            embedding_model=cast(
                EmbeddingModelBase,
                FakeEmbeddingModel(),
            ),
            vector_store=store,
            collection="knowledge",
        )
        await store.create_collection("knowledge", dimensions=2)
        await store.insert(
            "knowledge",
            [
                VectorRecord(
                    vector=[0.1, 0.2],
                    document_id="vector-document",
                    chunk=Chunk(
                        content=TextBlock(type="text", text="原始内容"),
                        source="guide.md",
                        chunk_index=0,
                        total_chunks=1,
                    ),
                ),
            ],
        )
        reader = QdrantChunkReader(knowledge_base)

        edited = await reader.update_text_chunk(
            "vector-document",
            0,
            content="人工修订内容",
            expected_content_hash=content_hash("原始内容"),
        )
        page = await reader.list_chunks("vector-document")

        assert edited.after_hash == content_hash("人工修订内容")
        assert isinstance(page.items[0].content, TextBlock)
        assert page.items[0].content.text == "人工修订内容"
        assert page.items[0].metadata["manual_edit_id"] == edited.edit_id

        with pytest.raises(ChunkEditConflictError, match="发生变化"):
            await reader.update_text_chunk(
                "vector-document",
                0,
                content="过期编辑",
                expected_content_hash=content_hash("原始内容"),
            )

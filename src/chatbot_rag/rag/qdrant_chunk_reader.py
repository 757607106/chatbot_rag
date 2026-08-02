"""从 Qdrant 读取真正参与召回的已索引切片。"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from agentscope.message import TextBlock
from agentscope.rag import Chunk, KnowledgeBase, QdrantStore


class ChunkReaderError(RuntimeError):
    """当前知识库无法提供切片浏览能力。"""


class ChunkEditConflictError(ChunkReaderError):
    """切片内容或活动索引已在编辑期间发生变化。"""


@dataclass(frozen=True, slots=True)
class ChunkPage:
    """按最终切片序号排序的一页索引内容。"""

    items: tuple[Chunk, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class ChunkEditResult:
    """一次已原子写入 Qdrant 的文本切片编辑结果。"""

    edit_id: str
    chunk: Chunk
    before_hash: str
    after_hash: str
    edited_at: str


class QdrantChunkReader:
    """通过 Qdrant 公开客户端读取指定向量文档的 payload。"""

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        """绑定与聊天检索相同的知识库句柄。"""
        vector_store = knowledge_base.vector_store
        if not isinstance(vector_store, QdrantStore):
            raise ChunkReaderError("当前向量存储不支持切片浏览。")
        self._store = vector_store
        self._knowledge_base = knowledge_base
        self._collection = knowledge_base.collection

    async def list_chunks(
        self,
        vector_document_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> ChunkPage:
        """读取一个向量文档的全部切片并在内存中稳定分页。

        Args:
            vector_document_id: AgentScope 写入 Qdrant 的文档标识。
            offset: 从零开始的切片偏移量。
            limit: 本页最大切片数量。

        Returns:
            与实际召回 payload 一致的切片页。

        Raises:
            ValueError: 分页参数无效时抛出。
        """
        if offset < 0:
            raise ValueError("offset must not be negative")
        if limit <= 0 or limit > 100:
            raise ValueError("limit must be between 1 and 100")

        from qdrant_client import models

        client = self._store.get_client()
        points: list[Any] = []
        scroll_offset: Any = None
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=vector_document_id),
                ),
            ],
        )
        while True:
            page, next_offset = await client.scroll(
                collection_name=self._collection,
                scroll_filter=query_filter,
                limit=256,
                offset=scroll_offset,
                with_payload=True,
                with_vectors=False,
            )
            points.extend(page)
            if next_offset is None:
                break
            scroll_offset = next_offset

        chunks = sorted(
            (
                Chunk.model_validate(
                    cast(dict[str, object], point.payload)["chunk"],
                )
                for point in points
            ),
            key=lambda chunk: chunk.chunk_index,
        )
        return ChunkPage(
            items=tuple(chunks[offset:offset + limit]),
            total=len(chunks),
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
        """重新嵌入并原子覆盖一个文本切片的向量和 payload。"""
        if chunk_index < 0:
            raise ValueError("chunk_index must not be negative")
        from qdrant_client import models

        await self._knowledge_base.ensure_collection()
        client = self._store.get_client()
        points, _ = await client.scroll(
            collection_name=self._collection,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=vector_document_id),
                    ),
                    models.FieldCondition(
                        key="chunk.chunk_index",
                        match=models.MatchValue(value=chunk_index),
                    ),
                ],
            ),
            limit=2,
            with_payload=True,
            with_vectors=False,
        )
        if len(points) != 1:
            raise ChunkReaderError("目标切片不存在或索引数据不唯一。")

        point = points[0]
        payload = cast(dict[str, object], point.payload)
        chunk = Chunk.model_validate(payload["chunk"])
        if not isinstance(chunk.content, TextBlock):
            raise ChunkReaderError("当前只支持编辑文本切片。")
        before_hash = content_hash(chunk.content.text)
        if before_hash != expected_content_hash:
            raise ChunkEditConflictError("切片已发生变化，请刷新后重试。")

        edit_id = uuid.uuid4().hex
        edited_at = datetime.now(UTC).isoformat()
        updated_chunk = chunk.model_copy(deep=True)
        updated_chunk.content = chunk.content.model_copy(
            update={"text": content},
        )
        updated_chunk.metadata = {
            **updated_chunk.metadata,
            "manual_edit_id": edit_id,
            "manual_edited_at": edited_at,
        }
        embedding = await self._knowledge_base.embedding_model(
            [updated_chunk.content],
        )
        if len(embedding.embeddings) != 1:
            raise ChunkReaderError("嵌入模型没有返回唯一切片向量。")

        await client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=point.id,
                    vector=embedding.embeddings[0],
                    payload={
                        "document_id": vector_document_id,
                        "chunk": updated_chunk.model_dump(mode="json"),
                    },
                ),
            ],
        )
        return ChunkEditResult(
            edit_id=edit_id,
            chunk=updated_chunk,
            before_hash=before_hash,
            after_hash=content_hash(content),
            edited_at=edited_at,
        )


def content_hash(content: str) -> str:
    """生成用于切片乐观并发控制的 SHA-256 摘要。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

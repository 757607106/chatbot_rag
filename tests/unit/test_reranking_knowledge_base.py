"""带重排序的 AgentScope 知识库测试。"""

from __future__ import annotations

from typing import Any, cast

import pytest
from agentscope.embedding import EmbeddingModelBase
from agentscope.message import TextBlock
from agentscope.rag import (
    Chunk,
    KnowledgeBase,
    VectorSearchResult,
    VectorStoreBase,
)

from chatbot_rag.models.reranker import RerankScore, RerankingError
from chatbot_rag.rag.reranking_knowledge_base import (
    RerankingKnowledgeBase,
    _normalize_queries,
)


def _result(index: int, text: str) -> VectorSearchResult:
    """创建一个可排序的向量命中。"""
    return VectorSearchResult(
        score=0.9 - index * 0.1,
        document_id=f"document-{index}",
        chunk=Chunk(
            content=TextBlock(text=text),
            source="产品配置.md",
            chunk_index=index,
            total_chunks=3,
            metadata={},
        ),
    )


@pytest.mark.asyncio
async def test_knowledge_base_reranks_expanded_vector_candidates(
    monkeypatch: Any,
) -> None:
    """知识库应扩大向量候选集、清理媒体标记并按模型索引精排。"""
    candidates = [
        _result(0, "产品乙专业版：在管理后台启用该功能。"),
        _result(
            1,
            "产品甲基础版：在客户端设置页启用该功能。\n"
            '<chatbot-media asset-id="'
            f"{'a' * 64}"
            '" />',
        ),
        _result(2, "产品甲专业版：由管理员统一配置。"),
    ]
    captured: dict[str, object] = {}

    async def fake_vector_search(
        self: KnowledgeBase,
        queries: list[object],
        top_k: int,
        score_threshold: float | None,
    ) -> list[VectorSearchResult]:
        del self
        captured["queries"] = queries
        captured["candidate_top_k"] = top_k
        captured["score_threshold"] = score_threshold
        return candidates

    class FakeReranker:
        """记录精排输入并把完全匹配对象与版本的候选排到首位。"""

        async def rerank(
            self,
            query: str,
            documents: list[str],
            top_n: int,
        ) -> list[RerankScore]:
            captured["query"] = query
            captured["documents"] = documents
            captured["top_n"] = top_n
            return [
                RerankScore(index=1, relevance_score=0.95),
                RerankScore(index=0, relevance_score=0.41),
            ]

    monkeypatch.setattr(KnowledgeBase, "search", fake_vector_search)
    knowledge_base = RerankingKnowledgeBase(
        name="knowledge",
        description="description",
        embedding_model=cast(EmbeddingModelBase, object()),
        vector_store=cast(VectorStoreBase, object()),
        collection="collection",
        reranker=FakeReranker(),
        candidate_top_k=50,
    )

    results = await knowledge_base.search(
        [TextBlock(text="web_user: 产品甲基础版如何启用该功能")],
        top_k=2,
    )

    assert captured["candidate_top_k"] == 50
    vector_queries = cast(list[object], captured["queries"])
    assert isinstance(vector_queries[0], TextBlock)
    assert vector_queries[0].text == "产品甲基础版如何启用该功能"
    assert captured["query"] == "产品甲基础版如何启用该功能"
    documents = cast(list[str], captured["documents"])
    assert "<chatbot-media" not in documents[1]
    assert all(
        document.startswith("文档来源：产品配置.md\n\n")
        for document in documents
    )
    assert captured["top_n"] == 2
    assert [result.chunk.chunk_index for result in results] == [1, 0]
    assert [result.score for result in results] == [0.95, 0.41]


@pytest.mark.asyncio
async def test_knowledge_base_never_appends_unreranked_candidates(
    monkeypatch: Any,
) -> None:
    """重排序成功后不得为凑足 Top K 补回未经模型确认的候选。"""
    candidates = [_result(0, "范围冲突的候选"), _result(1, "匹配候选")]

    async def fake_vector_search(
        self: KnowledgeBase,
        queries: list[object],
        top_k: int,
        score_threshold: float | None,
    ) -> list[VectorSearchResult]:
        del self, queries, top_k, score_threshold
        return candidates

    class SelectiveReranker:
        """模拟只确认一个候选的重排序边界替身。"""

        async def rerank(
            self,
            query: str,
            documents: list[str],
            top_n: int,
        ) -> list[RerankScore]:
            del query, documents, top_n
            return [RerankScore(index=1, relevance_score=0.88)]

    monkeypatch.setattr(KnowledgeBase, "search", fake_vector_search)
    knowledge_base = RerankingKnowledgeBase(
        name="knowledge",
        description="description",
        embedding_model=cast(EmbeddingModelBase, object()),
        vector_store=cast(VectorStoreBase, object()),
        collection="collection",
        reranker=SelectiveReranker(),
        candidate_top_k=50,
    )

    results = await knowledge_base.search(["查询"], top_k=2)

    assert [result.chunk.chunk_index for result in results] == [1]


@pytest.mark.asyncio
async def test_knowledge_base_falls_back_when_reranker_fails(
    monkeypatch: Any,
) -> None:
    """精排服务失败时应保留向量上下文，避免无资料调用生成模型。"""
    candidates = [_result(0, "候选一"), _result(1, "候选二")]

    async def fake_vector_search(
        self: KnowledgeBase,
        queries: list[object],
        top_k: int,
        score_threshold: float | None,
    ) -> list[VectorSearchResult]:
        del self, queries, top_k, score_threshold
        return candidates

    class FailingReranker:
        """模拟百炼重排序服务暂时不可用。"""

        async def rerank(
            self,
            query: str,
            documents: list[str],
            top_n: int,
        ) -> list[RerankScore]:
            del query, documents, top_n
            raise RerankingError("temporarily unavailable")

    monkeypatch.setattr(KnowledgeBase, "search", fake_vector_search)
    knowledge_base = RerankingKnowledgeBase(
        name="knowledge",
        description="description",
        embedding_model=cast(EmbeddingModelBase, object()),
        vector_store=cast(VectorStoreBase, object()),
        collection="collection",
        reranker=FailingReranker(),
        candidate_top_k=50,
    )

    results = await knowledge_base.search(["查询"], top_k=1)

    assert results == candidates[:1]


def test_query_normalization_preserves_domain_prefix() -> None:
    """问题本身的英文冒号前缀不得被误判为 AgentScope 说话人名称。"""
    queries = _normalize_queries(
        [
            TextBlock(text="HTTP: 500 错误如何处理"),
            TextBlock(text="web_user: 普通问题"),
        ],
    )

    assert isinstance(queries[0], TextBlock)
    assert queries[0].text == "HTTP: 500 错误如何处理"
    assert isinstance(queries[1], TextBlock)
    assert queries[1].text == "普通问题"

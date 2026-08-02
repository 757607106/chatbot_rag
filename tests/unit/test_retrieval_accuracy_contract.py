"""与具体业务问题无关的检索准确率契约测试。"""

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

from chatbot_rag.models.reranker import RerankScore
from chatbot_rag.rag.reranking_knowledge_base import RerankingKnowledgeBase


def _candidate(index: int, text: str, source: str) -> VectorSearchResult:
    """创建初始向量排名固定的候选结果。"""
    return VectorSearchResult(
        score=1.0 - index / 100,
        document_id=f"document-{index}",
        chunk=Chunk(
            content=TextBlock(text=text),
            source=source,
            chunk_index=index,
            total_chunks=30,
            metadata={},
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "conflicting", "answering", "answer_marker"),
    [
        (
            "A系统专业版在哪里修改审批人",
            "A系统基础版：在个人设置中修改审批人。",
            "A系统专业版：在组织管理的审批配置中修改审批人。",
            "组织管理的审批配置",
        ),
        (
            "2025版报表支持什么导出格式",
            "2024版报表仅支持导出 CSV。",
            "2025版报表支持导出 XLSX。",
            "导出 XLSX",
        ),
        (
            "华东仓库的库存上限是多少",
            "华南仓库的库存上限是 500 件。",
            "华东仓库的库存上限是 200 件。",
            "200 件",
        ),
    ],
)
async def test_expanded_recall_and_rerank_resolve_scope_conflicts(
    monkeypatch: Any,
    query: str,
    conflicting: str,
    answering: str,
    answer_marker: str,
) -> None:
    """正确证据向量排名靠后时，通用精排链路仍应按完整范围选中。"""
    candidates = [_candidate(0, conflicting, "冲突说明.md")]
    candidates.extend(
        _candidate(index, f"与问题无关的候选 {index}", "其他资料.md")
        for index in range(1, 22)
    )
    candidates.append(_candidate(22, answering, "正确说明.md"))
    captured: dict[str, object] = {}

    async def fake_vector_search(
        self: KnowledgeBase,
        queries: list[object],
        top_k: int,
        score_threshold: float | None,
    ) -> list[VectorSearchResult]:
        del self, score_threshold
        captured["queries"] = queries
        captured["top_k"] = top_k
        return candidates

    class ConstraintAwareReranker:
        """模拟按照完整显式约束确认直接证据的重排序模型。"""

        async def rerank(
            self,
            query: str,
            documents: list[str],
            top_n: int,
        ) -> list[RerankScore]:
            del query
            assert top_n == 1
            index = next(
                index
                for index, document in enumerate(documents)
                if answer_marker in document
            )
            return [RerankScore(index=index, relevance_score=0.93)]

    monkeypatch.setattr(KnowledgeBase, "search", fake_vector_search)
    knowledge_base = RerankingKnowledgeBase(
        name="knowledge",
        description="description",
        embedding_model=cast(EmbeddingModelBase, object()),
        vector_store=cast(VectorStoreBase, object()),
        collection="collection",
        reranker=ConstraintAwareReranker(),
        candidate_top_k=50,
    )

    results = await knowledge_base.search(
        [TextBlock(text=f"web_user: {query}")],
        top_k=1,
    )

    assert captured["top_k"] == 50
    vector_queries = cast(list[object], captured["queries"])
    assert isinstance(vector_queries[0], TextBlock)
    assert vector_queries[0].text == query
    assert len(results) == 1
    assert results[0].chunk.chunk_index == 22
    assert results[0].score == 0.93
    assert isinstance(results[0].chunk.content, TextBlock)
    assert answer_marker in results[0].chunk.content.text

"""在 AgentScope 原生知识库检索后执行文本重排序。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, cast

from agentscope.embedding import EmbeddingModelBase
from agentscope.message import DataBlock, TextBlock
from agentscope.rag import KnowledgeBase, VectorSearchResult, VectorStoreBase

from chatbot_rag.models.reranker import RerankingError, TextReranker
from chatbot_rag.rag.media_assets import strip_media_references

_SPEAKER_PREFIX_PATTERN = re.compile(r"^(?:web_user|user):\s*")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalTraceItem:
    """召回诊断中的一个候选及其阶段排名。"""

    result: VectorSearchResult
    vector_rank: int
    vector_score: float
    final_rank: int | None = None
    rerank_score: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    """一次向量召回与重排序的可公开诊断结果。"""

    query: str
    vector_candidates: tuple[RetrievalTraceItem, ...]
    final_results: tuple[RetrievalTraceItem, ...]
    rerank_status: Literal["succeeded", "skipped", "fallback"]
    vector_elapsed_ms: float
    rerank_elapsed_ms: float
    total_elapsed_ms: float


class RerankingKnowledgeBase(KnowledgeBase):  # type: ignore[misc]
    """扩展原生知识库，以 qwen3-rerank 精排向量召回候选。"""

    def __init__(
        self,
        name: str,
        description: str,
        embedding_model: EmbeddingModelBase,
        vector_store: VectorStoreBase,
        collection: str,
        reranker: TextReranker,
        candidate_top_k: int,
        metadata_filter: dict[str, object] | None = None,
    ) -> None:
        """使用原生知识库依赖和重排序策略初始化实例。

        Args:
            name: 面向智能体的知识库名称。
            description: 面向智能体的知识库描述。
            embedding_model: 索引和初始召回使用的嵌入模型。
            vector_store: 已进入异步上下文的向量存储。
            collection: 物理向量集合名称。
            reranker: 对初始召回候选执行精排的文本模型。
            candidate_top_k: 送入重排序模型的最大候选数。
            metadata_filter: 可选的知识库元数据隔离条件。

        Raises:
            ValueError: 候选数不是正整数时抛出。
        """
        if candidate_top_k <= 0:
            raise ValueError("candidate_top_k must be greater than zero")
        super().__init__(
            name=name,
            description=description,
            embedding_model=embedding_model,
            vector_store=vector_store,
            collection=collection,
            metadata_filter=metadata_filter,
        )
        self._reranker = reranker
        self._candidate_top_k = candidate_top_k

    async def search(
        self,
        queries: list[str | TextBlock | DataBlock],
        top_k: int = 5,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult]:
        """扩大向量召回范围，经文本重排序后返回最终 Top K。

        Args:
            queries: AgentScope RAG 中间件提供的原始检索输入。
            top_k: 重排序后返回的最大结果数。
            score_threshold: 初始向量召回阶段的最低相似度。

        Returns:
            按 qwen3-rerank 相关性降序排列的检索结果。重排序服务异常时
            返回原始向量排序，避免无上下文调用生成模型。
        """
        trace = await self.search_with_trace(
            queries=queries,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        return [item.result for item in trace.final_results]

    async def search_with_trace(
        self,
        queries: list[str | TextBlock | DataBlock],
        top_k: int = 5,
        score_threshold: float | None = None,
        candidate_top_k: int | None = None,
    ) -> RetrievalTrace:
        """执行与正式检索一致的流程并保留阶段排名和耗时。

        Args:
            queries: 等待嵌入和检索的查询列表。
            top_k: 重排序后返回的最大结果数。
            score_threshold: 向量召回阶段的最低相似度。
            candidate_top_k: 可选的诊断候选数量，默认使用运行时配置。

        Returns:
            不包含向量内容或内部模型响应的结构化诊断结果。

        Raises:
            ValueError: 排名数量超出有效范围时抛出。
        """
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        resolved_candidate_top_k = (
            self._candidate_top_k
            if candidate_top_k is None
            else candidate_top_k
        )
        if resolved_candidate_top_k < top_k:
            raise ValueError("candidate_top_k must not be less than top_k")
        if resolved_candidate_top_k > 500:
            raise ValueError("candidate_top_k must not exceed 500")

        started_at = time.perf_counter()
        normalized_queries = _normalize_queries(queries)
        vector_started_at = time.perf_counter()
        candidates = cast(
            list[VectorSearchResult],
            await super().search(
                queries=normalized_queries,
                top_k=resolved_candidate_top_k,
                score_threshold=score_threshold,
            ),
        )
        vector_elapsed_ms = _elapsed_ms(vector_started_at)
        query = _join_text_queries(normalized_queries)
        vector_items = tuple(
            RetrievalTraceItem(
                result=candidate,
                vector_rank=index,
                vector_score=candidate.score,
            )
            for index, candidate in enumerate(candidates, start=1)
        )
        if not candidates:
            return RetrievalTrace(
                query=query,
                vector_candidates=vector_items,
                final_results=(),
                rerank_status="skipped",
                vector_elapsed_ms=vector_elapsed_ms,
                rerank_elapsed_ms=0.0,
                total_elapsed_ms=_elapsed_ms(started_at),
            )

        rerankable: list[RetrievalTraceItem] = []
        documents: list[str] = []
        for item in vector_items:
            candidate = item.result
            if not isinstance(candidate.chunk.content, TextBlock):
                continue
            document = strip_media_references(candidate.chunk.content.text)
            if document:
                rerankable.append(item)
                documents.append(_format_rerank_document(candidate, document))
        if not query or not rerankable:
            final_items = tuple(
                RetrievalTraceItem(
                    result=item.result,
                    vector_rank=item.vector_rank,
                    vector_score=item.vector_score,
                    final_rank=index,
                )
                for index, item in enumerate(vector_items[:top_k], start=1)
            )
            return RetrievalTrace(
                query=query,
                vector_candidates=vector_items,
                final_results=final_items,
                rerank_status="skipped",
                vector_elapsed_ms=vector_elapsed_ms,
                rerank_elapsed_ms=0.0,
                total_elapsed_ms=_elapsed_ms(started_at),
            )

        rerank_started_at = time.perf_counter()
        try:
            scores = await self._reranker.rerank(
                query=query,
                documents=documents,
                top_n=min(top_k, len(documents)),
            )
        except (RerankingError, ValueError):
            logger.exception(
                "qwen3-rerank failed; falling back to vector ranking.",
            )
            rerank_elapsed_ms = _elapsed_ms(rerank_started_at)
            fallback_items = tuple(
                RetrievalTraceItem(
                    result=item.result,
                    vector_rank=item.vector_rank,
                    vector_score=item.vector_score,
                    final_rank=index,
                )
                for index, item in enumerate(vector_items[:top_k], start=1)
            )
            return RetrievalTrace(
                query=query,
                vector_candidates=vector_items,
                final_results=fallback_items,
                rerank_status="fallback",
                vector_elapsed_ms=vector_elapsed_ms,
                rerank_elapsed_ms=rerank_elapsed_ms,
                total_elapsed_ms=_elapsed_ms(started_at),
            )

        rerank_elapsed_ms = _elapsed_ms(rerank_started_at)
        final_items = tuple(
            RetrievalTraceItem(
                result=rerankable[score.index].result.model_copy(
                    update={"score": score.relevance_score},
                ),
                vector_rank=rerankable[score.index].vector_rank,
                vector_score=rerankable[score.index].vector_score,
                final_rank=index,
                rerank_score=score.relevance_score,
            )
            for index, score in enumerate(scores[:top_k], start=1)
        )
        return RetrievalTrace(
            query=query,
            vector_candidates=vector_items,
            final_results=final_items,
            rerank_status="succeeded",
            vector_elapsed_ms=vector_elapsed_ms,
            rerank_elapsed_ms=rerank_elapsed_ms,
            total_elapsed_ms=_elapsed_ms(started_at),
        )


def _normalize_queries(
    queries: list[str | TextBlock | DataBlock],
) -> list[str | TextBlock | DataBlock]:
    """移除 RAG 中间件添加的说话人前缀，避免污染向量查询。"""
    normalized: list[str | TextBlock | DataBlock] = []
    for query in queries:
        if isinstance(query, str):
            normalized.append(_strip_speaker_prefix(query))
        elif isinstance(query, TextBlock):
            normalized.append(
                query.model_copy(
                    update={"text": _strip_speaker_prefix(query.text)},
                ),
            )
        else:
            normalized.append(query)
    return normalized


def _join_text_queries(queries: list[str | TextBlock | DataBlock]) -> str:
    """合并文本查询，并移除静态中间件添加的说话人前缀。"""
    values: list[str] = []
    for query in queries:
        if isinstance(query, str):
            value = query
        elif isinstance(query, TextBlock):
            value = query.text
        else:
            continue
        normalized = _strip_speaker_prefix(value)
        if normalized:
            values.append(normalized)
    return "\n".join(values)


def _strip_speaker_prefix(value: str) -> str:
    """从一段查询文本开头移除一个 AgentScope 说话人标签。"""
    return _SPEAKER_PREFIX_PATTERN.sub("", value.strip(), count=1)


def _format_rerank_document(
    result: VectorSearchResult,
    document: str,
) -> str:
    """确保重排序模型始终能够看到候选的真实来源范围。"""
    source_context = f"文档来源：{result.chunk.source}"
    if document == source_context or document.startswith(f"{source_context}\n"):
        return document
    return f"{source_context}\n\n{document}"


def _elapsed_ms(started_at: float) -> float:
    """返回适合管理界面展示的毫秒耗时。"""
    return round((time.perf_counter() - started_at) * 1000, 2)

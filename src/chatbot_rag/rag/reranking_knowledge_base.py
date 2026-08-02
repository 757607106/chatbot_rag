"""在 AgentScope 原生知识库检索后执行文本重排序。"""

from __future__ import annotations

import logging
import re
from typing import cast

from agentscope.embedding import EmbeddingModelBase
from agentscope.message import DataBlock, TextBlock
from agentscope.rag import KnowledgeBase, VectorSearchResult, VectorStoreBase

from chatbot_rag.models.reranker import RerankingError, TextReranker
from chatbot_rag.rag.media_assets import strip_media_references

_SPEAKER_PREFIX_PATTERN = re.compile(r"^(?:web_user|user):\s*")

logger = logging.getLogger(__name__)


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
        normalized_queries = _normalize_queries(queries)
        candidate_top_k = max(top_k, self._candidate_top_k)
        candidates = cast(
            list[VectorSearchResult],
            await super().search(
                queries=normalized_queries,
                top_k=candidate_top_k,
                score_threshold=score_threshold,
            ),
        )
        if not candidates:
            return []

        query = _join_text_queries(normalized_queries)
        rerankable: list[VectorSearchResult] = []
        documents: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate.chunk.content, TextBlock):
                continue
            document = strip_media_references(candidate.chunk.content.text)
            if document:
                rerankable.append(candidate)
                documents.append(_format_rerank_document(candidate, document))
        if not query or not rerankable:
            return candidates[:top_k]
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
            return candidates[:top_k]

        return [
            rerankable[score.index].model_copy(
                update={"score": score.relevance_score},
            )
            for score in scores
        ][:top_k]


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

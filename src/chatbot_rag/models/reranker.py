"""使用百炼 qwen3-rerank 对向量召回候选进行重排序。"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Protocol

from dashscope import TextReRank

RERANK_INSTRUCTION = (
    "Given a user question, rank passages by whether they provide evidence "
    "that directly answers it. Every explicitly named entity, attribute, "
    "version, environment, and applicability constraint must match. Treat a "
    "passage with any conflicting constraint as not answering the question."
)
RERANK_REQUEST_TIMEOUT_SECONDS = 15
RERANK_MAX_ATTEMPTS = 2


class RerankingError(RuntimeError):
    """百炼重排序请求或响应无效时抛出的异常。"""


class TextReranker(Protocol):
    """知识库重排序阶段所需的最小模型边界。"""

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[RerankScore]:
        """返回按相关性降序排列的候选索引和分数。

        Args:
            query: 用户的原始检索问题。
            documents: 待重排序的候选文本。
            top_n: 需要返回的最高相关候选数量。

        Returns:
            按相关性降序排列的候选索引和分数。
        """
        ...


@dataclass(frozen=True, slots=True)
class RerankScore:
    """一个候选文档的重排序位置和相关性分数。"""

    index: int
    relevance_score: float


class QwenTextReranker:
    """通过 DashScope SDK 调用 qwen3-rerank 文本重排序模型。"""

    def __init__(
        self,
        api_key: str,
        model_name: str = "qwen3-rerank",
        request: Callable[..., Any] | None = None,
    ) -> None:
        """使用凭据、模型名称和可选请求替身初始化重排序器。

        Args:
            api_key: 百炼 API Key。
            model_name: 文本重排序模型名称。
            request: 测试时可注入的同步 DashScope 请求函数。
        """
        self._api_key = api_key
        self._model_name = model_name
        self._request = request or TextReRank.call

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[RerankScore]:
        """按照问题解答相关性重排候选文档。

        Args:
            query: 用户的原始检索问题。
            documents: 向量召回得到的候选文本，顺序与索引一一对应。
            top_n: 需要返回的最高相关候选数量。

        Returns:
            按相关性降序排列的候选索引和分数。

        Raises:
            ValueError: 查询、候选或 ``top_n`` 无效时抛出。
            RerankingError: 百炼请求失败或响应结构无效时抛出。
        """
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if not documents:
            return []
        if top_n <= 0:
            raise ValueError("top_n must be greater than zero")

        expected_count = min(top_n, len(documents))
        response: Any | None = None
        request_error: Exception | None = None
        for _ in range(RERANK_MAX_ATTEMPTS):
            try:
                response = await asyncio.to_thread(
                    self._request,
                    model=self._model_name,
                    query=normalized_query,
                    documents=documents,
                    top_n=expected_count,
                    return_documents=False,
                    instruct=RERANK_INSTRUCTION,
                    api_key=self._api_key,
                    request_timeout=RERANK_REQUEST_TIMEOUT_SECONDS,
                )
                break
            except Exception as error:
                request_error = error
        if response is None:
            raise RerankingError(
                "qwen3-rerank request failed",
            ) from request_error
        if getattr(response, "status_code", None) != HTTPStatus.OK:
            code = getattr(response, "code", "unknown_error") or "unknown_error"
            raise RerankingError(f"qwen3-rerank request failed: {code}")

        output = getattr(response, "output", None)
        results = getattr(output, "results", None)
        if not isinstance(results, list):
            raise RerankingError("qwen3-rerank returned invalid results")

        parsed: list[RerankScore] = []
        seen_indexes: set[int] = set()
        for result in results:
            index = getattr(result, "index", None)
            relevance_score = getattr(result, "relevance_score", None)
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
                or index >= len(documents)
                or index in seen_indexes
                or not isinstance(relevance_score, (int, float))
                or isinstance(relevance_score, bool)
                or not math.isfinite(relevance_score)
            ):
                raise RerankingError(
                    "qwen3-rerank returned an invalid candidate",
                )
            seen_indexes.add(index)
            parsed.append(
                RerankScore(
                    index=index,
                    relevance_score=float(relevance_score),
                ),
            )
        if len(parsed) != expected_count:
            raise RerankingError(
                "qwen3-rerank returned an incomplete result set",
            )
        return sorted(
            parsed,
            key=lambda score: score.relevance_score,
            reverse=True,
        )

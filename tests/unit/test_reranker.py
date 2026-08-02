"""百炼 qwen3-rerank 适配器测试。"""

from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

import pytest

from chatbot_rag.models.reranker import (
    QwenTextReranker,
    RERANK_INSTRUCTION,
    RerankingError,
)


@pytest.mark.asyncio
async def test_qwen_reranker_maps_ranked_indexes() -> None:
    """适配器应传递问答排序指令并按相关性分数稳定排序。"""
    captured: dict[str, object] = {}

    def fake_request(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                results=[
                    SimpleNamespace(index=1, relevance_score=0.42),
                    SimpleNamespace(index=0, relevance_score=0.91),
                ],
            ),
        )

    reranker = QwenTextReranker(
        api_key="secret",
        model_name="qwen3-rerank",
        request=fake_request,
    )

    scores = await reranker.rerank(
        query="产品甲基础版如何启用功能",
        documents=["产品甲基础版设置", "产品乙专业版设置"],
        top_n=2,
    )

    assert [score.index for score in scores] == [0, 1]
    assert [score.relevance_score for score in scores] == [0.91, 0.42]
    assert captured["model"] == "qwen3-rerank"
    assert captured["instruct"] == RERANK_INSTRUCTION
    assert captured["return_documents"] is False
    assert captured["api_key"] == "secret"


@pytest.mark.asyncio
async def test_qwen_reranker_rejects_failed_response() -> None:
    """服务端失败必须转换为不包含响应细节的重排序异常。"""

    def fake_request(**kwargs: object) -> object:
        del kwargs
        return SimpleNamespace(
            status_code=HTTPStatus.BAD_REQUEST,
            code="InvalidParameter",
            message="sensitive upstream details",
        )

    reranker = QwenTextReranker(api_key="secret", request=fake_request)

    with pytest.raises(RerankingError, match="InvalidParameter") as error:
        await reranker.rerank("查询", ["候选"], top_n=1)

    assert "sensitive upstream details" not in str(error.value)


@pytest.mark.asyncio
async def test_qwen_reranker_rejects_invalid_candidate_index() -> None:
    """越界或重复索引不得进入知识库排序结果。"""

    def fake_request(**kwargs: object) -> object:
        del kwargs
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                results=[SimpleNamespace(index=2, relevance_score=0.9)],
            ),
        )

    reranker = QwenTextReranker(api_key="secret", request=fake_request)

    with pytest.raises(RerankingError, match="invalid candidate"):
        await reranker.rerank("查询", ["候选"], top_n=1)


@pytest.mark.asyncio
async def test_qwen_reranker_wraps_transport_error() -> None:
    """网络层异常必须转换为知识库可以执行回退的统一异常。"""
    attempts = 0

    def fake_request(**kwargs: object) -> object:
        nonlocal attempts
        del kwargs
        attempts += 1
        raise TimeoutError("provider timeout details")

    reranker = QwenTextReranker(api_key="secret", request=fake_request)

    with pytest.raises(RerankingError, match="request failed") as error:
        await reranker.rerank("查询", ["候选"], top_n=1)

    assert attempts == 2
    assert "provider timeout details" not in str(error.value)


@pytest.mark.asyncio
async def test_qwen_reranker_retries_one_transient_transport_error() -> None:
    """第一次网络调用失败后应执行一次有界重试并接受正常结果。"""
    attempts = 0

    def fake_request(**kwargs: object) -> object:
        nonlocal attempts
        del kwargs
        attempts += 1
        if attempts == 1:
            raise TimeoutError("transient timeout")
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                results=[SimpleNamespace(index=0, relevance_score=0.87)],
            ),
        )

    reranker = QwenTextReranker(api_key="secret", request=fake_request)

    scores = await reranker.rerank("查询", ["候选"], top_n=1)

    assert attempts == 2
    assert scores[0].relevance_score == 0.87


@pytest.mark.asyncio
async def test_qwen_reranker_rejects_incomplete_result_set() -> None:
    """服务返回少于请求数量的候选时不得静默接受不完整精排。"""

    def fake_request(**kwargs: object) -> object:
        del kwargs
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                results=[SimpleNamespace(index=0, relevance_score=0.9)],
            ),
        )

    reranker = QwenTextReranker(api_key="secret", request=fake_request)

    with pytest.raises(RerankingError, match="incomplete result set"):
        await reranker.rerank("查询", ["候选一", "候选二"], top_n=2)

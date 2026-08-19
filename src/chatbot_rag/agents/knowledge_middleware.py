"""知识库检索中间件的统一装配。"""

from __future__ import annotations

from collections.abc import Sequence

from agentscope.middleware import RAGMiddleware
from agentscope.rag import KnowledgeBase

from chatbot_rag.config import Settings


def create_knowledge_middleware(
    settings: Settings,
    knowledge_bases: Sequence[KnowledgeBase],
) -> RAGMiddleware:
    """创建文本聊天与实时语音共用的知识库检索中间件。

    Args:
        settings: 经过校验的运行时配置。
        knowledge_bases: 本次调用可检索的全部知识库句柄；传入多个时
            模型可通过 ``search_knowledge`` 的 ``knowledge_bases`` 参数
            选择检索范围，默认知识库应排在首位。

    Returns:
        暴露 ``search_knowledge`` 的 AgentScope agentic RAG 中间件。
    """
    return RAGMiddleware(
        knowledge_bases=list(knowledge_bases),
        parameters=RAGMiddleware.Parameters(
            mode="agentic",
            top_k=settings.rag_top_k,
        ),
    )

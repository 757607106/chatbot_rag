"""知识库工具的统一装配。"""

from agentscope.middleware import RAGMiddleware
from agentscope.rag import KnowledgeBase

from chatbot_rag.config import Settings


def create_knowledge_middleware(
    settings: Settings,
    knowledge_base: KnowledgeBase,
) -> RAGMiddleware:
    """创建文本聊天与实时语音共用的知识库工具中间件。

    Args:
        settings: 经过校验的运行时配置。
        knowledge_base: AgentScope 原生知识库句柄。

    Returns:
        暴露 ``search_knowledge`` 的 AgentScope agentic RAG 中间件。
    """
    return RAGMiddleware(
        knowledge_bases=[knowledge_base],
        parameters=RAGMiddleware.Parameters(
            mode="agentic",
            top_k=settings.rag_top_k,
        ),
    )

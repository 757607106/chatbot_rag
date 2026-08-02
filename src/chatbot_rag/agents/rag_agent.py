"""使用 AgentScope 2.0.5 装配 RAG 智能体。"""

from agentscope.agent import Agent
from agentscope.middleware import RAGMiddleware
from agentscope.rag import KnowledgeBase

from chatbot_rag.config import Settings
from chatbot_rag.models import create_chat_model

SYSTEM_PROMPT = """You are a careful retrieval-augmented assistant.
Answer from the retrieved context, cite its source labels when available, and do
not invent facts. If retrieval does not provide enough evidence, say what
information is missing.
"""


def create_rag_agent(
    settings: Settings,
    knowledge_base: KnowledgeBase,
) -> Agent:
    """创建已配置的 AgentScope RAG 智能体。

    Args:
        settings: 经过校验的运行时配置。
        knowledge_base: AgentScope 原生知识库句柄。

    Returns:
        完成配置的 AgentScope 智能体。
    """
    rag_middleware = RAGMiddleware(
        knowledge_bases=[knowledge_base],
        parameters=RAGMiddleware.Parameters(
            mode="static",
            top_k=settings.rag_top_k,
            persist_hint=False,
        ),
    )

    return Agent(
        name=settings.agent_name,
        system_prompt=SYSTEM_PROMPT,
        model=create_chat_model(settings),
        middlewares=[rag_middleware],
    )

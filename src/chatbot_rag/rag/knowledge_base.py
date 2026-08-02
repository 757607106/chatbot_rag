"""AgentScope 知识库及向量存储生命周期。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agentscope.rag import KnowledgeBase, QdrantStore

from chatbot_rag.config import Settings
from chatbot_rag.models import create_embedding_model

KNOWLEDGE_BASE_DESCRIPTION = "用于回答项目资料相关问题的知识库。"


@asynccontextmanager
async def open_knowledge_base(
    settings: Settings,
) -> AsyncIterator[KnowledgeBase]:
    """打开与应用生命周期一致的 AgentScope 知识库。

    Args:
        settings: 经过校验的应用配置。

    Yields:
        已连接 Qdrant 向量存储的知识库句柄。
    """
    vector_store = _create_vector_store(settings)
    async with vector_store:
        yield KnowledgeBase(
            name=settings.knowledge_base_name,
            description=KNOWLEDGE_BASE_DESCRIPTION,
            embedding_model=create_embedding_model(settings),
            vector_store=vector_store,
            collection=settings.knowledge_collection,
        )


def _create_vector_store(settings: Settings) -> QdrantStore:
    """根据配置创建本地或远程 Qdrant 存储。"""
    if settings.qdrant_url is not None:
        return QdrantStore(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )

    settings.qdrant_path.mkdir(parents=True, exist_ok=True)
    return QdrantStore(path=str(settings.qdrant_path))

"""AgentScope 知识库及向量存储生命周期。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agentscope.rag import KnowledgeBase, QdrantStore

from chatbot_rag.config import Settings
from chatbot_rag.models import QwenTextReranker, create_embedding_model
from chatbot_rag.rag.reranking_knowledge_base import RerankingKnowledgeBase

KNOWLEDGE_BASE_DESCRIPTION = "用于回答项目资料相关问题的知识库。"


class KnowledgeBaseRuntimeFactory:
    """在共享向量存储连接上创建独立知识库句柄。"""

    def __init__(self, settings: Settings, vector_store: QdrantStore) -> None:
        """复用嵌入模型、重排器和 Qdrant 连接。"""
        self._embedding_model = create_embedding_model(settings)
        self._vector_store = vector_store
        self._reranker = QwenTextReranker(
            api_key=settings.dashscope_api_key,
            model_name=settings.rerank_model_name,
        )
        self._candidate_top_k = settings.rerank_candidate_top_k

    def create(
        self,
        *,
        name: str,
        description: str,
        collection: str,
    ) -> RerankingKnowledgeBase:
        """创建只访问指定物理 collection 的逻辑知识库。"""
        return RerankingKnowledgeBase(
            name=name,
            description=description,
            embedding_model=self._embedding_model,
            vector_store=self._vector_store,
            collection=collection,
            reranker=self._reranker,
            candidate_top_k=self._candidate_top_k,
        )


@asynccontextmanager
async def open_knowledge_base_runtime(
    settings: Settings,
) -> AsyncIterator[KnowledgeBaseRuntimeFactory]:
    """打开可供多个知识库共享的 Qdrant 生命周期。"""
    vector_store = _create_vector_store(settings)
    async with vector_store:
        yield KnowledgeBaseRuntimeFactory(settings, vector_store)


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
    async with open_knowledge_base_runtime(settings) as runtime:
        yield runtime.create(
            name=settings.knowledge_base_name,
            description=KNOWLEDGE_BASE_DESCRIPTION,
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

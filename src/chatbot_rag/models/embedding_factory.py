"""AgentScope 嵌入模型实例工厂。"""

from agentscope.credential import DashScopeCredential
from agentscope.embedding import DashScopeEmbeddingModel

from chatbot_rag.config import Settings


def create_embedding_model(settings: Settings) -> DashScopeEmbeddingModel:
    """创建用于知识库索引和查询的 DashScope 嵌入模型。

    Args:
        settings: 经过校验的应用配置。

    Returns:
        AgentScope DashScope 嵌入模型。
    """
    credential = DashScopeCredential(api_key=settings.dashscope_api_key)
    return DashScopeEmbeddingModel(
        credential=credential,
        model=settings.embedding_model_name,
        dimensions=settings.embedding_dimensions,
    )

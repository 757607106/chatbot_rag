"""AgentScope 模型实例工厂。"""

from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel

from chatbot_rag.config import Settings

DashScopeChatParameters = DashScopeChatModel.Parameters


def create_chat_model(settings: Settings) -> DashScopeChatModel:
    """创建已配置的 AgentScope DashScope 聊天模型。

    Args:
        settings: 经过校验的应用配置。

    Returns:
        AgentScope DashScope 聊天模型。
    """
    credential = DashScopeCredential(api_key=settings.dashscope_api_key)
    return DashScopeChatModel(
        credential=credential,
        model=settings.model_name,
        parameters=DashScopeChatParameters(
            temperature=0.1,
            top_p=0.8,
        ),
    )

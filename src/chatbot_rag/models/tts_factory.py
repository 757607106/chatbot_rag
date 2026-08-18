"""AgentScope 语音合成模型工厂。"""

from agentscope.credential import DashScopeCredential
from agentscope.tts import DashScopeCosyVoiceTTSModel

from chatbot_rag.config import Settings


def create_tts_model(settings: Settings) -> DashScopeCosyVoiceTTSModel:
    """创建百炼 Qwen-Audio-TTS 语音合成模型。

    ``DashScopeCosyVoiceTTSModel`` 是 AgentScope 对 ``dashscope.audio.tts_v2``
    WebSocket 合成入口的封装；百炼 Qwen-Audio-TTS（如
    ``qwen-audio-3.0-tts-plus``）与 CosyVoice 共用该 SDK 入口，通过
    ``model`` 参数区分。API Key 取自 ``DASHSCOPE_API_KEY``，如需覆盖
    WebSocket 端点可设置 dashscope 原生环境变量
    ``DASHSCOPE_WEBSOCKET_BASE_URL``。

    Args:
        settings: 经过校验的应用配置。

    Returns:
        非流式聚合输出的语音合成模型，每次调用返回完整 WAV 音频。
    """
    credential = DashScopeCredential(api_key=settings.dashscope_api_key)
    return DashScopeCosyVoiceTTSModel(
        credential=credential,
        model=settings.tts_model_name,
        parameters=DashScopeCosyVoiceTTSModel.Parameters(
            voice=settings.tts_voice,
        ),
        stream=False,
    )

"""语音合成应用用例。"""

from __future__ import annotations

import base64

from agentscope.message import Base64Source
from agentscope.tts import TTSModelBase, TTSResponse


class SpeechSynthesisError(RuntimeError):
    """语音合成失败或返回内容不可用时抛出的异常。"""


class SpeechSynthesisService:
    """把文本合成为可直接播放的 WAV 音频。"""

    def __init__(self, tts_model: TTSModelBase) -> None:
        """绑定非流式聚合输出的 TTS 模型边界。"""
        self._tts_model = tts_model

    async def synthesize(self, text: str) -> bytes:
        """合成完整 WAV 音频字节。

        Args:
            text: 待合成文本，调用前应完成长度与空白校验。

        Returns:
            24kHz 单声道 16 位 WAV 音频字节。

        Raises:
            SpeechSynthesisError: 模型调用失败、返回流式增量或音频内容
                缺失时抛出。
        """
        try:
            response = await self._tts_model.synthesize(text)
        except SpeechSynthesisError:
            raise
        except Exception as error:
            raise SpeechSynthesisError(f"语音合成调用失败：{error}") from error
        if not isinstance(response, TTSResponse):
            raise SpeechSynthesisError(
                "语音合成模型返回了流式增量，服务要求非流式聚合输出",
            )
        content = response.content
        if content is None or not isinstance(content.source, Base64Source):
            raise SpeechSynthesisError("语音合成结果中没有音频内容")
        try:
            audio = base64.b64decode(content.source.data, validate=True)
        except (ValueError, TypeError) as error:
            raise SpeechSynthesisError("语音合成音频数据无法解码") from error
        if not audio:
            raise SpeechSynthesisError("语音合成音频内容为空")
        return audio

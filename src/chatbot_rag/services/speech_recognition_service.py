"""语音识别应用用例。"""

from __future__ import annotations

from chatbot_rag.models import (
    SpeechRecognitionModel,
    SpeechRecognitionModelError,
    SpeechRecognitionModelResult,
)


class SpeechRecognitionError(RuntimeError):
    """语音识别失败或没有得到可用文本。"""


class SpeechRecognitionService:
    """使用百炼 ASR 把浏览器录音转换为输入文本。"""

    def __init__(self, model: SpeechRecognitionModel) -> None:
        """绑定语音识别模型边界。"""
        self._model = model

    async def transcribe(
        self,
        audio: bytes,
        media_type: str,
    ) -> SpeechRecognitionModelResult:
        """识别一段已完成边界校验的音频。"""
        try:
            return await self._model.transcribe(audio, media_type)
        except SpeechRecognitionModelError as error:
            raise SpeechRecognitionError(str(error)) from error
        except Exception as error:
            raise SpeechRecognitionError(
                f"语音识别调用失败：{error}",
            ) from error

"""百炼语音识别模型适配与构造。"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Protocol

from dashscope import MultiModalConversation

from chatbot_rag.config import Settings


class SpeechRecognitionModelError(RuntimeError):
    """百炼语音识别调用失败或响应格式无效。"""


@dataclass(frozen=True, slots=True)
class SpeechRecognitionModelResult:
    """模型返回的语音转写结果。"""

    text: str
    language: str | None = None
    emotion: str | None = None


class SpeechRecognitionModel(Protocol):
    """语音识别服务依赖的最小模型边界。"""

    async def transcribe(
        self,
        audio: bytes,
        media_type: str,
    ) -> SpeechRecognitionModelResult:
        """把一段音频转换为文本。"""


class DashScopeSpeechRecognitionModel:
    """通过百炼 Qwen3-ASR-Flash 识别短音频。"""

    def __init__(self, api_key: str, model: str, language: str) -> None:
        """保存经过配置层校验的百炼调用参数。"""
        self._api_key = api_key
        self._model = model
        self._language = language

    async def transcribe(
        self,
        audio: bytes,
        media_type: str,
    ) -> SpeechRecognitionModelResult:
        """在线程池中执行 DashScope 同步 SDK 调用。"""
        data_url = (
            f"data:{media_type};base64,"
            f"{base64.b64encode(audio).decode('ascii')}"
        )
        try:
            response = await asyncio.to_thread(
                MultiModalConversation.call,
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": [{"audio": data_url}],
                    },
                ],
                api_key=self._api_key,
                result_format="message",
                asr_options={
                    "language": self._language,
                    "enable_itn": True,
                },
            )
        except Exception as error:
            raise SpeechRecognitionModelError(
                f"语音识别模型调用失败：{error}",
            ) from error
        return _parse_model_response(response)


def create_asr_model(settings: Settings) -> SpeechRecognitionModel:
    """创建使用系统环境变量凭据的百炼语音识别模型。"""
    return DashScopeSpeechRecognitionModel(
        api_key=settings.dashscope_api_key,
        model=settings.asr_model_name,
        language=settings.asr_language,
    )


def _parse_model_response(response: Any) -> SpeechRecognitionModelResult:
    """从 DashScope 动态响应中提取稳定的转写字段。"""
    status_code = getattr(response, "status_code", None)
    if status_code != HTTPStatus.OK:
        code = str(getattr(response, "code", "unknown"))
        raise SpeechRecognitionModelError(
            f"语音识别模型返回错误状态：{status_code} ({code})",
        )

    output = _as_mapping(getattr(response, "output", None))
    choices = output.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SpeechRecognitionModelError("语音识别响应缺少 choices")
    choice = _as_mapping(choices[0])
    message = _as_mapping(choice.get("message"))
    content = message.get("content")

    text_parts: list[str] = []
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for item in content:
            item_mapping = _as_mapping(item)
            text = item_mapping.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
    transcript = "".join(text_parts).strip()
    if not transcript:
        raise SpeechRecognitionModelError("语音识别结果为空")

    language: str | None = None
    emotion: str | None = None
    annotations = message.get("annotations")
    if isinstance(annotations, list):
        for item in annotations:
            annotation = _as_mapping(item)
            if language is None and isinstance(annotation.get("language"), str):
                language = annotation["language"]
            if emotion is None and isinstance(annotation.get("emotion"), str):
                emotion = annotation["emotion"]
    return SpeechRecognitionModelResult(
        text=transcript,
        language=language,
        emotion=emotion,
    )


def _as_mapping(value: object) -> Mapping[str, Any]:
    """把 DashScope DictMixin 或普通字典收敛为只读映射。"""
    if isinstance(value, Mapping):
        return value
    return {}

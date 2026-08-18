"""百炼实时语音 WebSocket 连接边界。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import AsyncContextManager, Protocol, cast
from urllib.parse import urlencode

from websockets.asyncio.client import connect as websocket_connect


class RealtimeVoiceConnection(Protocol):
    """实时语音服务所需的最小上游连接接口。"""

    async def send(self, message: str) -> None:
        """发送一个 JSON 文本事件。"""

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        """迭代上游返回的事件。"""


class RealtimeVoiceConnectionFactory(Protocol):
    """为每个浏览器会话创建独立的上游连接。"""

    def connect(self) -> AsyncContextManager[RealtimeVoiceConnection]:
        """打开一个已鉴权的百炼实时语音连接。"""


class DashScopeRealtimeVoiceConnectionFactory:
    """创建仅在服务端持有凭据的百炼 Realtime 连接。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
    ) -> None:
        """保存经过配置层校验的连接参数。"""
        self._api_key = api_key
        self._url = f"{base_url}?{urlencode({'model': model_name})}"

    @property
    def url(self) -> str:
        """返回不含凭据的最终 WebSocket 地址。"""
        return self._url

    def connect(self) -> AsyncContextManager[RealtimeVoiceConnection]:
        """打开百炼连接并在退出时可靠关闭。"""
        return self._open_connection()

    @asynccontextmanager
    async def _open_connection(
        self,
    ) -> AsyncIterator[RealtimeVoiceConnection]:
        async with websocket_connect(
            self._url,
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
            },
            compression=None,
            max_size=2 * 1024 * 1024,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
        ) as connection:
            yield cast(RealtimeVoiceConnection, connection)

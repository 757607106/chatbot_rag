"""文档图片资产仓库与 HTTP 路由测试。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import cast

import httpx
import pytest

from chatbot_rag.rag import (
    MediaAssetError,
    MediaAssetNotFoundError,
    MediaAssetStore,
)
from chatbot_rag.services import ChatService
from chatbot_rag.services.api import create_app

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
    "nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=",
)


def test_media_store_persists_embedded_image_and_prunes_orphan(
    tmp_path: Path,
) -> None:
    """内嵌图片应持久化，并在源文档移除后完成清理。"""
    store = MediaAssetStore(tmp_path / "media", ())
    asset_id = store.register_embedded(
        PNG_BYTES,
        filename="步骤.png",
        identity="guide.docx#image-0",
    )
    store.commit_document("guide.docx", {asset_id})

    assert store.has_document("guide.docx") is True
    assert store.describe(asset_id).filename == "步骤.png"

    store.prune_documents(set())

    assert store.has_document("guide.docx") is False
    with pytest.raises(MediaAssetNotFoundError):
        store.describe(asset_id)


@pytest.mark.asyncio
async def test_media_store_downloads_allowed_remote_image_once(
    tmp_path: Path,
) -> None:
    """远程图片应校验主机与文件签名后按需缓存。"""
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.host == "images.example.com"
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=PNG_BYTES,
        )

    store = MediaAssetStore(
        tmp_path / "media",
        ("images.example.com",),
        transport=httpx.MockTransport(handler),
    )
    asset_id = store.register_remote(
        "https://images.example.com/manual/step.png",
        filename="操作步骤.png",
        identity="manual.md#image-0",
    )

    first = await store.materialize(asset_id)
    second = await store.materialize(asset_id)

    assert first.path.read_bytes() == PNG_BYTES
    assert second.media_type == "image/png"
    assert requests == 1


@pytest.mark.asyncio
async def test_media_store_downloads_allowed_http_remote_image(
    tmp_path: Path,
) -> None:
    """HTTP 远程图片应与 HTTPS 一样通过校验并按需缓存。"""
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.host == "images.example.com"
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=PNG_BYTES,
        )

    store = MediaAssetStore(
        tmp_path / "media",
        ("images.example.com",),
        transport=httpx.MockTransport(handler),
    )
    asset_id = store.register_remote(
        "http://images.example.com/manual/step.png",
        filename="操作步骤.png",
        identity="manual.md#image-0",
    )

    first = await store.materialize(asset_id)
    second = await store.materialize(asset_id)

    assert first.path.read_bytes() == PNG_BYTES
    assert second.media_type == "image/png"
    assert requests == 1


def test_media_store_rejects_remote_host_outside_allowlist(
    tmp_path: Path,
) -> None:
    """未明确允许的远程主机不得进入后端图片代理。"""
    store = MediaAssetStore(tmp_path / "media", ("safe.example.com",))

    with pytest.raises(MediaAssetError, match="允许范围"):
        store.register_remote(
            "https://unsafe.example.com/image.png",
            filename="image.png",
            identity="manual.md#image-0",
        )


def test_media_store_rejects_non_http_scheme(
    tmp_path: Path,
) -> None:
    """非 HTTP/HTTPS 协议的远程图片不得登记。"""
    store = MediaAssetStore(tmp_path / "media", ("images.example.com",))

    with pytest.raises(MediaAssetError, match="允许范围"):
        store.register_remote(
            "ftp://images.example.com/image.png",
            filename="image.png",
            identity="manual.md#image-0",
        )


@pytest.mark.asyncio
async def test_media_route_returns_embedded_image_inline(
    tmp_path: Path,
) -> None:
    """媒体 API 应返回可内联显示且禁止 MIME 猜测的图片。"""
    store = MediaAssetStore(tmp_path / "media", ())
    asset_id = store.register_embedded(
        PNG_BYTES,
        filename="步骤.png",
        identity="guide.docx#image-0",
    )
    store.commit_document("guide.docx", {asset_id})
    app = create_app(
        chat_service=cast(ChatService, object()),
        media_store=store,
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/media/{asset_id}")

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("inline")

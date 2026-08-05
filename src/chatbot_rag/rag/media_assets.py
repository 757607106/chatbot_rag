"""文档图片资产的注册、持久化与受控读取。"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal, cast
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MEDIA_REFERENCE_PATTERN = re.compile(
    r'<chatbot-media asset-id="(?P<asset_id>[0-9a-f]{64})"\s*/>',
)
_ASSET_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_REMOTE_CONTENT_TYPES = {
    "application/octet-stream",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
_MEDIA_EXTENSIONS = {
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class MediaAssetError(RuntimeError):
    """图片资产无法安全注册或读取。"""


class MediaAssetNotFoundError(MediaAssetError):
    """请求的图片资产不存在。"""


class MediaAssetUnavailableError(MediaAssetError):
    """远程图片当前无法取得或内容不符合要求。"""


class _AssetRecord(BaseModel):  # type: ignore[misc]
    """持久化到磁盘的单个图片资产描述。"""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    kind: Literal["embedded", "remote"]
    filename: str
    media_type: str | None = None
    remote_url: str | None = None


class _DocumentManifest(BaseModel):  # type: ignore[misc]
    """一个源文档当前引用的图片集合。"""

    model_config = ConfigDict(extra="forbid")

    source: str
    asset_ids: list[str]


@dataclass(frozen=True, slots=True)
class MediaFile:
    """可由 HTTP 层直接返回的本地图片文件。"""

    path: Path
    media_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class MediaAssetDescriptor:
    """可安全进入聊天协议的图片资产描述。"""

    asset_id: str
    filename: str


class MediaAssetStore:
    """管理文档图片元数据、本地内容及远程图片缓存。"""

    def __init__(
        self,
        root: Path,
        allowed_remote_hosts: tuple[str, ...],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """创建图片资产仓库。

        Args:
            root: 图片元数据、清单和缓存文件的根目录。
            allowed_remote_hosts: 允许后端代理的 HTTP/HTTPS 图片主机。
            transport: 仅用于测试替换远程 HTTP 传输。
        """
        self._root = root
        self._assets_path = root / "assets"
        self._manifests_path = root / "manifests"
        self._allowed_remote_hosts = frozenset(
            host.lower().rstrip(".") for host in allowed_remote_hosts
        )
        self._transport = transport
        self._download_locks: dict[str, asyncio.Lock] = {}
        self._assets_path.mkdir(parents=True, exist_ok=True)
        self._manifests_path.mkdir(parents=True, exist_ok=True)

    def register_embedded(
        self,
        data: bytes,
        filename: str,
        identity: str,
    ) -> str:
        """保存文档内嵌图片并返回稳定资产标识。

        Args:
            data: 图片二进制内容。
            filename: 用于界面展示的原始文件名。
            identity: 包含源文档和图片位置的稳定身份。

        Returns:
            六十四位十六进制资产标识。

        Raises:
            MediaAssetError: 内容不是受支持的浏览器图片格式时抛出。
        """
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise MediaAssetError("图片内容为空或超过 10 MB 限制。")
        media_type = sniff_image_media_type(data)
        if media_type is None:
            raise MediaAssetError("文档图片格式不受支持。")

        asset_id = _asset_id("embedded", identity, data)
        safe_filename = _safe_filename(filename, media_type)
        self._write_asset_record(
            _AssetRecord(
                asset_id=asset_id,
                kind="embedded",
                filename=safe_filename,
                media_type=media_type,
            ),
        )
        content_path = self._content_path(asset_id)
        if not content_path.exists():
            _atomic_write_bytes(content_path, data)
        return asset_id

    def register_remote(
        self,
        url: str,
        filename: str,
        identity: str,
    ) -> str:
        """登记允许代理的远程 HTTP/HTTPS 图片。

        Args:
            url: 原始图片地址，仅保存在服务端。
            filename: 用于界面展示的文件名或替代文字。
            identity: 包含源文档和出现位置的稳定身份。

        Returns:
            六十四位十六进制资产标识。

        Raises:
            MediaAssetError: URL 不满足协议、主机或凭据约束时抛出。
        """
        normalized_url = self._validate_remote_url(url)
        asset_id = _asset_id(
            "remote",
            identity,
            normalized_url.encode("utf-8"),
        )
        self._write_asset_record(
            _AssetRecord(
                asset_id=asset_id,
                kind="remote",
                filename=_safe_filename(
                    filename or _filename_from_url(normalized_url),
                ),
                remote_url=normalized_url,
            ),
        )
        return asset_id

    def commit_document(self, source: str, asset_ids: set[str]) -> None:
        """原子更新一个文档当前使用的图片清单。"""
        ordered_ids = sorted(asset_ids)
        for asset_id in ordered_ids:
            self.get_record(asset_id)
        manifest = _DocumentManifest(
            source=source,
            asset_ids=ordered_ids,
        )
        _atomic_write_text(
            self._manifest_path(source),
            manifest.model_dump_json(indent=2),
        )

    def has_document(self, source: str) -> bool:
        """检查文档图片清单及其本地必需文件是否完整。"""
        path = self._manifest_path(source)
        if not path.is_file():
            return False
        try:
            manifest = _DocumentManifest.model_validate_json(
                path.read_text(encoding="utf-8"),
            )
            if manifest.source != source:
                return False
            for asset_id in manifest.asset_ids:
                record = self.get_record(asset_id)
                if (
                    record.kind == "embedded"
                    and not self._content_path(asset_id).is_file()
                ):
                    return False
        except (OSError, ValidationError, MediaAssetError):
            return False
        return True

    def prune_documents(self, active_sources: set[str]) -> None:
        """删除已移除文档的清单和不再被任何文档引用的图片。"""
        manifests: list[_DocumentManifest] = []
        for path in sorted(self._manifests_path.glob("*.json")):
            try:
                manifest = _DocumentManifest.model_validate_json(
                    path.read_text(encoding="utf-8"),
                )
            except (OSError, ValidationError) as error:
                raise MediaAssetError(
                    f"图片清单损坏：{path.name}",
                ) from error
            if manifest.source not in active_sources:
                path.unlink()
                continue
            manifests.append(manifest)

        self._prune_unreferenced_assets(manifests)

    def delete_document(self, source: str) -> None:
        """删除一个文档的图片清单并清理无引用资产。"""
        manifest_path = self._manifest_path(source)
        if manifest_path.exists():
            manifest_path.unlink()

        manifests: list[_DocumentManifest] = []
        for path in sorted(self._manifests_path.glob("*.json")):
            try:
                manifests.append(
                    _DocumentManifest.model_validate_json(
                        path.read_text(encoding="utf-8"),
                    ),
                )
            except (OSError, ValidationError) as error:
                raise MediaAssetError(
                    f"图片清单损坏：{path.name}",
                ) from error
        self._prune_unreferenced_assets(manifests)

    def _prune_unreferenced_assets(
        self,
        manifests: list[_DocumentManifest],
    ) -> None:
        """根据当前清单删除不再被引用的图片记录和内容。"""

        referenced = {
            asset_id
            for manifest in manifests
            for asset_id in manifest.asset_ids
        }
        for record_path in sorted(self._assets_path.glob("*.json")):
            asset_id = record_path.stem
            if asset_id in referenced:
                continue
            record_path.unlink()
            content_path = self._content_path(asset_id)
            if content_path.exists():
                content_path.unlink()

    def get_record(self, asset_id: str) -> _AssetRecord:
        """读取并严格校验图片资产元数据。"""
        if _ASSET_ID_PATTERN.fullmatch(asset_id) is None:
            raise MediaAssetNotFoundError("图片资产标识无效。")
        path = self._record_path(asset_id)
        try:
            record = cast(
                _AssetRecord,
                _AssetRecord.model_validate_json(
                    path.read_text(encoding="utf-8"),
                ),
            )
        except FileNotFoundError as error:
            raise MediaAssetNotFoundError("图片资产不存在。") from error
        except (OSError, ValidationError) as error:
            raise MediaAssetError("图片资产元数据损坏。") from error
        if record.asset_id != asset_id:
            raise MediaAssetError("图片资产元数据标识不一致。")
        return record

    async def materialize(self, asset_id: str) -> MediaFile:
        """确保图片位于本地缓存并返回可发送文件描述。"""
        record = self.get_record(asset_id)
        content_path = self._content_path(asset_id)
        if record.kind == "remote" and not content_path.is_file():
            lock = self._download_locks.setdefault(
                asset_id,
                asyncio.Lock(),
            )
            async with lock:
                if not content_path.is_file():
                    record = await self._download_remote(record)

        if not content_path.is_file() or record.media_type is None:
            raise MediaAssetUnavailableError("图片内容当前不可用。")
        return MediaFile(
            path=content_path,
            media_type=record.media_type,
            filename=record.filename,
        )

    def public_url(self, asset_id: str) -> str:
        """返回浏览器通过同源 BFF 访问图片的公开路径。"""
        self.get_record(asset_id)
        return f"/api/media/{asset_id}"

    def describe(self, asset_id: str) -> MediaAssetDescriptor:
        """返回不包含磁盘路径和远程源地址的公开图片描述。"""
        record = self.get_record(asset_id)
        return MediaAssetDescriptor(
            asset_id=record.asset_id,
            filename=record.filename,
        )

    async def _download_remote(self, record: _AssetRecord) -> _AssetRecord:
        """下载并验证一个远程图片，成功后原子写入缓存。"""
        if record.remote_url is None:
            raise MediaAssetError("远程图片缺少源地址。")
        url = self._validate_remote_url(record.remote_url)
        timeout = httpx.Timeout(10.0, connect=5.0)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                transport=self._transport,
                trust_env=False,
            ) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise MediaAssetUnavailableError(
                            "远程图片返回了非成功状态。",
                        )
                    content_type = response.headers.get(
                        "content-type",
                        "",
                    ).split(";", maxsplit=1)[0].lower()
                    if content_type not in _ALLOWED_REMOTE_CONTENT_TYPES:
                        raise MediaAssetUnavailableError(
                            "远程资源不是允许的图片类型。",
                        )
                    content_length = response.headers.get("content-length")
                    if (
                        content_length is not None
                        and int(content_length) > MAX_IMAGE_BYTES
                    ):
                        raise MediaAssetUnavailableError(
                            "远程图片超过 10 MB 限制。",
                        )

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_IMAGE_BYTES:
                            raise MediaAssetUnavailableError(
                                "远程图片超过 10 MB 限制。",
                            )
        except (httpx.HTTPError, ValueError) as error:
            raise MediaAssetUnavailableError(
                "远程图片暂时无法下载。",
            ) from error

        media_type = sniff_image_media_type(bytes(body))
        if media_type is None:
            raise MediaAssetUnavailableError("远程内容不是受支持的图片。")
        updated = cast(
            _AssetRecord,
            record.model_copy(update={"media_type": media_type}),
        )
        await asyncio.to_thread(
            _atomic_write_bytes,
            self._content_path(record.asset_id),
            bytes(body),
        )
        await asyncio.to_thread(self._write_asset_record, updated)
        return updated

    def _validate_remote_url(self, url: str) -> str:
        """验证远程地址只使用允许主机上的标准 HTTP 或 HTTPS。"""
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower().rstrip(".")
        try:
            port = parsed.port
        except ValueError as error:
            raise MediaAssetError("远程图片端口无效。") from error
        if scheme == "https":
            allowed_ports: tuple[int | None, ...] = (None, 443)
        elif scheme == "http":
            allowed_ports = (None, 80)
        else:
            allowed_ports = ()
        if (
            not allowed_ports
            or not host
            or host not in self._allowed_remote_hosts
            or parsed.username is not None
            or parsed.password is not None
            or port not in allowed_ports
            or not parsed.path
        ):
            raise MediaAssetError("远程图片地址不在允许范围内。")
        return url

    def _write_asset_record(self, record: _AssetRecord) -> None:
        """原子写入图片资产元数据。"""
        _atomic_write_text(
            self._record_path(record.asset_id),
            record.model_dump_json(indent=2),
        )

    def _record_path(self, asset_id: str) -> Path:
        return self._assets_path / f"{asset_id}.json"

    def _content_path(self, asset_id: str) -> Path:
        return self._assets_path / f"{asset_id}.bin"

    def _manifest_path(self, source: str) -> Path:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return self._manifests_path / f"{digest}.json"


def format_media_reference(asset_id: str) -> str:
    """创建只供协议层识别、不包含服务端路径的媒体标记。"""
    if _ASSET_ID_PATTERN.fullmatch(asset_id) is None:
        raise ValueError("asset_id must be a SHA-256 hex digest")
    return f'<chatbot-media asset-id="{asset_id}" />'


def extract_media_asset_ids(value: str) -> list[str]:
    """按首次出现顺序提取文本中的去重媒体标识。"""
    return list(
        dict.fromkeys(
            match.group("asset_id")
            for match in MEDIA_REFERENCE_PATTERN.finditer(value)
        ),
    )


def strip_media_references(value: str) -> str:
    """移除只供协议层消费的内部图片引用。"""
    return MEDIA_REFERENCE_PATTERN.sub("", value).strip()


def sniff_image_media_type(data: bytes) -> str | None:
    """通过文件签名识别浏览器可安全显示的常见图片格式。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    return None


def _asset_id(kind: str, identity: str, content: bytes) -> str:
    """根据来源位置和内容生成稳定且不可枚举的资产标识。"""
    value = b"\0".join(
        [kind.encode("utf-8"), identity.encode("utf-8"), content],
    )
    return hashlib.sha256(value).hexdigest()


def _safe_filename(
    value: str,
    media_type: str | None = None,
) -> str:
    """移除路径和控制字符并限制用户可见文件名长度。"""
    normalized = "".join(
        character
        for character in PurePath(value.strip()).name
        if character.isprintable() and character not in "\r\n\t"
    )
    if not normalized:
        normalized = "文档图片"
    suffix = Path(normalized).suffix.lower()
    if not suffix and media_type in _MEDIA_EXTENSIONS:
        normalized += _MEDIA_EXTENSIONS[media_type]
    return normalized[:180]


def _filename_from_url(url: str) -> str:
    """从远程 URL 路径提取不含查询参数的文件名。"""
    return unquote(PurePath(urlsplit(url).path).name) or "远程图片"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """在同一目录通过替换方式原子写入二进制内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(data)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _atomic_write_text(path: Path, value: str) -> None:
    """使用 UTF-8 原子写入小型元数据文件。"""
    _atomic_write_bytes(path, value.encode("utf-8"))

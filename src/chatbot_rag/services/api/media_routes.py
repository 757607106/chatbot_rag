"""文档图片的受控 HTTP 读取路由。"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Request, status
from fastapi.responses import FileResponse

from chatbot_rag.rag import (
    MediaAssetError,
    MediaAssetNotFoundError,
    MediaAssetStore,
    MediaAssetUnavailableError,
)

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/{asset_id}", response_class=FileResponse)
async def get_media_asset(
    asset_id: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    request: Request,
) -> FileResponse:
    """返回已登记文档图片，不暴露原始文件路径或远程地址。

    Args:
        asset_id: 内容与来源共同生成的稳定图片标识。
        request: 携带图片资产仓库的当前 FastAPI 请求。

    Returns:
        浏览器可内联显示的图片文件响应。

    Raises:
        HTTPException: 图片不存在、缓存失败或元数据损坏时抛出。
    """
    media_store = cast(
        MediaAssetStore | None,
        getattr(request.app.state, "media_store", None),
    )
    if media_store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="图片资源不存在。",
        )
    try:
        media_file = await media_store.materialize(asset_id)
    except MediaAssetNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="图片资源不存在。",
        ) from error
    except MediaAssetUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="图片资源暂时不可用。",
        ) from error
    except MediaAssetError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="图片资源无法读取。",
        ) from error

    return FileResponse(
        path=media_file.path,
        media_type=media_file.media_type,
        filename=media_file.filename,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )

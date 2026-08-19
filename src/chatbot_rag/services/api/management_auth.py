"""管理 API 的共享密钥鉴权依赖。"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

_MANAGEMENT_API_KEY_HEADER = "X-Api-Key"


def require_management_api_key(request: Request) -> None:
    """校验管理请求携带的共享密钥。

    ``CHATBOT_MANAGEMENT_API_KEY`` 未配置时管理 API 保持本地开发的
    开放行为；配置后所有管理请求必须携带匹配的 ``X-Api-Key`` 头，
    用于保护上传、删除、回滚等破坏性操作和知识库内容读取。
    """
    expected = getattr(request.app.state, "management_api_key", None)
    if expected is None:
        return
    provided = request.headers.get(_MANAGEMENT_API_KEY_HEADER, "")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="管理密钥缺失或不正确。",
        )

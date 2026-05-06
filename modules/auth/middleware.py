"""Session 驗證 middleware — Phase 2。

設計：
  - Cookie-based session（rule-api-design 指定）
  - 簽章用 itsdangerous TimestampSigner + SF_SESSION_SECRET
  - 兩段式：middleware 解碼注入 request.state.session（不阻擋）；
    `Depends(require_session)` 才強制 401
  - 8 小時 absolute timeout、HttpOnly + Secure + SameSite=Strict（rule-auth）

公開 API：
  - SessionMiddleware: ASGI 中介層，掛在 main.py
  - issue_session(response, user_id): 登入時呼叫，set 簽章 cookie
  - revoke_session(response): 登出時呼叫，刪 cookie
  - require_session: FastAPI dependency，無 session 直接 401
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from config import settings

logger = logging.getLogger(__name__)

# --- 常數 ---

COOKIE_NAME = "sf_session"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60  # 8 小時 absolute timeout（rule-auth）
SIGNER_SALT = "sf-session-v1"  # 換 salt 等同強制全體登出


# --- 簽章 helper ---


def _signer() -> TimestampSigner:
    """每次取用都重讀 settings，方便測試 monkey-patch。"""
    secret = settings.SESSION_SECRET
    if not secret or len(secret) < 32:
        # rule-auth：JWT/Session 簽章金鑰至少 256 bit (32 bytes)
        raise RuntimeError(
            "SF_SESSION_SECRET not configured or too short "
            "(must be ≥ 32 bytes)"
        )
    return TimestampSigner(secret, salt=SIGNER_SALT)


def _encode(payload: str) -> str:
    return _signer().sign(payload.encode("utf-8")).decode("ascii")


def _decode(raw: str) -> dict[str, Any] | None:
    """成功回傳 session payload，失敗回 None（簽章錯／過期）。"""
    try:
        unsigned = _signer().unsign(
            raw, max_age=SESSION_MAX_AGE_SECONDS
        ).decode("utf-8")
    except SignatureExpired:
        logger.info("session expired")
        return None
    except BadSignature:
        logger.warning("session bad signature")
        return None

    # payload 格式：sid:user_id
    sid, _, user_id = unsigned.partition(":")
    if not sid or not user_id:
        return None
    return {"sid": sid, "user_id": user_id}


# --- 公開 API（讓 route 層用） ---


def issue_session(response: Response, user_id: str = "admin") -> str:
    """登入成功時呼叫；產生新 session id（rule-auth 指定 regenerate）。

    Returns:
        新的 session id（也可寫入 audit log）。
    """
    sid = secrets.token_urlsafe(32)  # CSPRNG，≥256 bit（rule-auth）
    raw = _encode(f"{sid}:{user_id}")

    response.set_cookie(
        COOKIE_NAME,
        raw,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,             # rule-auth: JS 不可讀
        secure=not settings.DEBUG, # rule-auth: HTTPS only（本機 DEBUG 例外）
        samesite="strict",         # rule-api-design 要求
        path="/",
    )
    return sid


def revoke_session(response: Response) -> None:
    """登出時呼叫。Cookie 端立即失效；server 端目前無 revocation list
    （單一管理員場景，登出後再用同 cookie 也已被 max-age 限制）。
    """
    response.delete_cookie(COOKIE_NAME, path="/")


def require_session(request: Request) -> dict:
    """FastAPI dependency：無有效 session 直接 401。"""
    sess = getattr(request.state, "session", None)
    if not sess:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            # WWW-Authenticate header 對 cookie auth 不需要
        )
    return sess


# --- ASGI middleware（掛在 main.py） ---


class SessionMiddleware(BaseHTTPMiddleware):
    """解碼 cookie 注入 request.state.session（不負責阻擋）。

    阻擋邏輯由各 route 用 Depends(require_session) 控制。
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        raw = request.cookies.get(COOKIE_NAME)
        request.state.session = _decode(raw) if raw else None
        return await call_next(request)

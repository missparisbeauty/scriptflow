"""auth route — Phase 5。

職責：
  - POST /api/v1/auth/login  比對 ADMIN_PASSWORD，產 session cookie
  - POST /api/v1/auth/logout 撤銷 cookie
  - 失敗統一回 401（rule-auth：不分「帳號不存在」「密碼錯」）
  - 用 secrets.compare_digest 做常數時間比對（防 timing attack）
  - rate limit 在 main.py 統一掛載
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Response

from config import settings
from domain.exceptions import InvalidInput, ScriptFlowError
from domain.responses import ok
from modules.auth.middleware import issue_session, revoke_session
from modules.auth.schema import LoginRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class AuthFailed(ScriptFlowError):
    """登入失敗（rule-auth：訊息統一不洩漏）。"""

    error_code = "AUTH_FAILED"
    http_status = 401


@router.post("/login")
def login(req: LoginRequest, response: Response) -> dict:
    expected = settings.ADMIN_PASSWORD
    if not expected:
        # 後端設定缺漏，回 503 比較貼切，但對外仍走 AUTH_FAILED 不洩漏
        logger.error("auth.login admin_password not configured")
        raise AuthFailed("authentication failed")

    if not secrets.compare_digest(req.password, expected):
        logger.warning("auth.login failed result=invalid_password")
        raise AuthFailed("authentication failed")

    sid = issue_session(response, user_id="admin")
    logger.info("auth.login ok sid=%s", sid[:8] + "...")
    return ok({"user_id": "admin"})


@router.post("/logout")
def logout(response: Response) -> dict:
    revoke_session(response)
    return ok({"logged_out": True})

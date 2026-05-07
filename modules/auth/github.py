"""GitHub OAuth 登入 — Phase 7 補強。

職責：
  - GET /api/v1/auth/github/start    產 state、redirect 到 GitHub 同意頁
  - GET /api/v1/auth/github/callback 接 code、換 token、查 username、簽 session

設計：
  - state 用 CSPRNG 產生，存簽章 cookie（10 分鐘 TTL）→ 防 CSRF
  - username 必須在 ADMIN_GITHUB_USERS 白名單才放行
  - 成功後簽現有 session cookie（與密碼登入共用）
  - 失敗一律 redirect 回首頁帶 ?auth_error=...，不走 JSON error（OAuth 流程）

rule-auth：
  - state 用 secrets.token_urlsafe → CSPRNG
  - 不接受任意 redirect，redirect_uri 寫死在後端
  - access_token 不寫進 log
"""

from __future__ import annotations

import logging
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Query, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from config import settings
from modules.auth.middleware import issue_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/github", tags=["auth"])

# --- 常數 ---

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

OAUTH_STATE_COOKIE = "sf_oauth_state"
OAUTH_STATE_TTL_SECONDS = 10 * 60
OAUTH_STATE_SALT = "sf-github-oauth-state-v1"

GITHUB_HTTP_TIMEOUT = 15

# 失敗時 redirect 到首頁，前端讀 query 顯示錯誤訊息
LOGIN_ERROR_REDIRECT = "/?auth_error={msg}"
LOGIN_SUCCESS_REDIRECT = "/"


# --- helpers ---


def _state_signer() -> TimestampSigner:
    secret = settings.SESSION_SECRET
    if not secret or len(secret) < 32:
        raise RuntimeError("SF_SESSION_SECRET not configured for OAuth state")
    return TimestampSigner(secret, salt=OAUTH_STATE_SALT)


def _sign_state(value: str) -> str:
    return _state_signer().sign(value.encode("utf-8")).decode("ascii")


def _verify_state(signed: str) -> str | None:
    try:
        return (
            _state_signer()
            .unsign(signed, max_age=OAUTH_STATE_TTL_SECONDS)
            .decode("utf-8")
        )
    except (SignatureExpired, BadSignature):
        return None


def _allowed_users() -> set[str]:
    raw = (settings.ADMIN_GITHUB_USERS or "").strip()
    if not raw:
        return set()
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def _redirect_uri_from(request: Request) -> str:
    """組 redirect_uri，必須跟 GitHub OAuth App 設定完全一致。

    在 Cloud Run 後端：
      - 容器內收到的是 HTTP（內部 loopback）
      - 真實協定在 X-Forwarded-Proto header
      - 真實 host 在 X-Forwarded-Host 或 host header
    優先用 FRONTEND_ORIGIN env 寫死（最穩），否則動態組。
    """
    # Option 1: 環境變數寫死（推薦）
    frontend = os.getenv("FRONTEND_ORIGIN", "").rstrip("/")
    if frontend:
        return f"{frontend}/api/v1/auth/github/callback"

    # Option 2: 從 forwarded headers 動態判斷（reverse proxy 友善）
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    return f"{proto}://{host}/api/v1/auth/github/callback"


def _err_redirect(msg: str) -> RedirectResponse:
    """跳回首頁帶錯誤代碼（避免在 URL 裡放 stack trace）。"""
    safe_msg = msg.replace(" ", "_")[:60]
    return RedirectResponse(
        url=LOGIN_ERROR_REDIRECT.format(msg=safe_msg),
        status_code=303,
    )


# --- 對外 endpoints ---


@router.get("/start")
def start(request: Request) -> RedirectResponse:
    """產 state、寫 cookie、redirect 到 GitHub 同意頁。"""
    if not settings.GITHUB_CLIENT_ID:
        logger.error("github.start client_id not configured")
        return _err_redirect("github_not_configured")

    state = secrets.token_urlsafe(32)
    signed = _sign_state(state)

    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": _redirect_uri_from(request),
        "scope": "read:user",
        "state": state,
        "allow_signup": "false",
    }
    url = f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"

    resp = RedirectResponse(url=url, status_code=303)
    resp.set_cookie(
        OAUTH_STATE_COOKIE,
        signed,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="lax",  # GitHub 跳回來時要帶 cookie，strict 會擋
        path="/",
    )
    logger.info("github.start redirect")
    return resp


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    sf_oauth_state: str | None = Cookie(None),
) -> Response:
    """處理 GitHub 回呼：驗 state → 換 token → 查 user → 發 session cookie。"""
    if error:
        logger.warning("github.callback denied error=%s", error)
        return _err_redirect("github_denied")
    if not code or not state:
        return _err_redirect("missing_code_or_state")
    if not sf_oauth_state:
        return _err_redirect("state_cookie_missing")

    expected_state = _verify_state(sf_oauth_state)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        logger.warning("github.callback state mismatch")
        return _err_redirect("state_mismatch")

    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        logger.error("github.callback client credentials not configured")
        return _err_redirect("github_not_configured")

    # Step 1: code → access_token
    try:
        token = _exchange_code_for_token(code, _redirect_uri_from(request))
    except Exception as e:
        logger.error(
            "github.callback token_exchange_failed err=%s", type(e).__name__
        )
        return _err_redirect("token_exchange_failed")

    # Step 2: token → username
    try:
        username = _fetch_github_username(token)
    except Exception as e:
        logger.error(
            "github.callback fetch_user_failed err=%s", type(e).__name__
        )
        return _err_redirect("fetch_user_failed")

    if not username:
        return _err_redirect("no_username")

    # Step 3: 白名單比對（小寫不分大小寫）
    if username.lower() not in _allowed_users():
        logger.warning(
            "github.callback unauthorized username=%s allow=%d",
            username,
            len(_allowed_users()),
        )
        return _err_redirect("not_authorized")

    # Step 4: 簽 session、清 state cookie
    resp = RedirectResponse(url=LOGIN_SUCCESS_REDIRECT, status_code=303)
    issue_session(resp, user_id=username)
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    logger.info("github.callback ok user=%s", username)
    return resp


# --- 本機開發專用：一鍵登入（生產不開放） ---


@router.post("/dev-login")
def dev_login() -> Response:
    """DEBUG 模式下的一鍵登入 — 跳過 GitHub OAuth。

    生產（DEBUG=False）時回 404，等同不存在。
    """
    if not settings.DEBUG:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="not found")

    # 用白名單第一個 username，沒設就 "dev"
    users = _allowed_users()
    user_id = next(iter(users)) if users else "dev"

    resp = RedirectResponse(url="/", status_code=303)
    issue_session(resp, user_id=user_id)
    logger.info("dev_login bypass user=%s (DEBUG only)", user_id)
    return resp


# --- 環境資訊（讓前端知道當前是不是 DEBUG）---


@router.get("/env")
def env_info() -> dict:
    """前端用來判斷是否顯示 DEV 登入按鈕。"""
    return {
        "is_debug": bool(settings.DEBUG),
        "github_configured": bool(settings.GITHUB_CLIENT_ID),
    }


# --- 內部：呼叫 GitHub API ---


def _exchange_code_for_token(code: str, redirect_uri: str) -> str:
    """換 access_token。失敗拋 RuntimeError。"""
    payload = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    headers = {"Accept": "application/json"}
    with httpx.Client(timeout=GITHUB_HTTP_TIMEOUT) as client:
        r = client.post(GITHUB_TOKEN_URL, data=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(
            f"github_no_access_token error={data.get('error', 'unknown')}"
        )
    return token  # 不寫進 log（rule-auth）


def _fetch_github_username(token: str) -> str:
    """用 access_token 拉 user info。"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=GITHUB_HTTP_TIMEOUT) as client:
        r = client.get(GITHUB_USER_URL, headers=headers)
        r.raise_for_status()
        data = r.json()
    return (data.get("login") or "").strip()

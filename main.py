"""ScriptFlow FastAPI 啟動點。

Phase 0：/health（公開）
Phase 2：SessionMiddleware + /api/v1/health（需 session）
Phase 5+：在此檔做 DI 組裝、掛 module router
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from modules.auth.middleware import SessionMiddleware, require_session

app = FastAPI(
    title="ScriptFlow",
    version="0.2.0",
    # 生產環境關閉 API 文件頁面（vibecoding-safety）
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# --- 安全標頭 middleware（rule-cloud） ---

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # CSP 在 Phase 6 前端完成後再細調
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'"
    ),
}
if not settings.DEBUG:
    # HSTS 只在 HTTPS 啟用時送
    _SECURITY_HEADERS[
        "Strict-Transport-Security"
    ] = "max-age=31536000; includeSubDomains"


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


# --- Session 驗證 middleware（解碼 cookie，不阻擋） ---

# 注意：FastAPI middleware 執行順序為 LIFO，下方先 add 的後執行（外層）
# 我們希望 Session 解碼比安全標頭更早（內層），所以後加。
app.add_middleware(SessionMiddleware)


# --- 公開端點 ---


@app.get("/health")
def health() -> dict[str, str]:
    """公開健康檢查（Cloud Run probe 用）。"""
    return {"status": "ok"}


# --- 需驗證端點（Phase 2 完成條件） ---


@app.get("/api/v1/health")
def health_authed(session: dict = Depends(require_session)) -> dict:
    """需 session 的健康檢查；Phase 2 完成條件。"""
    return {"status": "ok", "user": session["user_id"]}


# --- 靜態檔 ---

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

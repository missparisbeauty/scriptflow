"""ScriptFlow FastAPI 啟動點。

Phase 0：/health（公開）
Phase 2：SessionMiddleware + /api/v1/health（需 session）+ 安全標頭
Phase 5：掛 module router + 集中 error handler + APScheduler 排程
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import scheduler
from config import settings
from domain.exceptions import ScriptFlowError
from domain.responses import err, ok
from modules.auth.middleware import SessionMiddleware, require_session
from modules.auth.route import router as auth_router
from modules.candidates.route import router as candidates_router
from modules.crawler.route import router as crawler_router
from modules.script.route import router as script_router
from modules.storyboard.route import router as storyboard_router
from modules.tracking.route import router as tracking_router

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# --- lifespan: 啟動 / 關閉 排程 ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


# --- Rate Limiter（rule-api：登入 5/min；一般 60/min） ---

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


app = FastAPI(
    title="ScriptFlow",
    version="0.5.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)
app.state.limiter = limiter


# --- CORS（rule-cloud：禁 *，限白名單） ---

_cors_origins = [
    o.strip()
    for o in (settings.GCP_PROJECT_ID, "")  # 暫無 FRONTEND_ORIGIN 設定
    if False  # 預設不開 CORS（前後同網域）
]
# 開發時若 DEBUG=true，允許 localhost 各埠
if settings.DEBUG:
    _cors_origins = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1",
    ]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


# --- 安全標頭 middleware（rule-cloud） ---

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'"
    ),
}
if not settings.DEBUG:
    _SECURITY_HEADERS["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


# --- Session middleware ---

app.add_middleware(SessionMiddleware)


# --- 集中 error handler（rule-backend / rule-cloud） ---


@app.exception_handler(ScriptFlowError)
async def handle_script_flow_error(request: Request, exc: ScriptFlowError):
    return JSONResponse(
        status_code=exc.http_status,
        content=err(exc.error_code, exc.message),
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    code = _http_status_to_code(exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content=err(code, str(exc.detail)),
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    # 不回完整 stack；簡化欄位錯誤
    fields = [
        {"loc": list(e["loc"]), "msg": e["msg"]}
        for e in exc.errors()[:5]
    ]
    return JSONResponse(
        status_code=400,
        content={
            "data": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "request body invalid",
                "fields": fields,
            },
        },
    )


@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content=err("RATE_LIMITED", "too many requests"),
    )


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception):
    # 不暴露內部錯誤（rule-cloud）
    logger.exception("unexpected error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=err("INTERNAL_ERROR", "internal server error"),
    )


def _http_status_to_code(status: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        429: "RATE_LIMITED",
    }.get(status, "ERROR")


# --- 公開端點 ---


@app.get("/health")
def health() -> dict[str, str]:
    """公開健康檢查（Cloud Run probe 用）。"""
    return {"status": "ok"}


# --- 需驗證端點 ---


@app.get("/api/v1/health")
def health_authed(session: dict = Depends(require_session)) -> dict:
    return ok({"status": "ok", "user": session["user_id"]})


@app.get("/api/v1/scheduler/status")
def scheduler_status(session: dict = Depends(require_session)) -> dict:
    return ok(scheduler.get_status())


# --- 掛載 module routers ---

# auth router 不依賴 session（自己負責登入），其他都需要
app.include_router(auth_router)
app.include_router(candidates_router)
app.include_router(crawler_router)
app.include_router(script_router)
app.include_router(storyboard_router)
app.include_router(tracking_router)


# --- 靜態檔 ---

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

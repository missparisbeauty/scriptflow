"""ScriptFlow FastAPI 啟動點 — Phase 0 骨架。

完成條件（dev-order.md Phase 0）：
  - `uvicorn main:app --reload` 啟動無錯誤
  - `GET /health` 回傳 {"status": "ok"}
  - 後續 Phase 在此檔做 DI 組裝（注入 infra 到 service）
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings

app = FastAPI(
    title="ScriptFlow",
    version="0.1.0",
    # 生產環境關閉 API 文件頁面（vibecoding-safety 要求）
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)


@app.get("/health")
def health() -> dict[str, str]:
    """簡易健康檢查端點，供 Cloud Run / 監控用。"""
    return {"status": "ok"}


# 靜態檔（Phase 6 才會有實際內容）
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

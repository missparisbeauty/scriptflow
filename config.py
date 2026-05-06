"""集中讀取環境變數。

所有 secret 透過環境變數注入，禁止 hardcode（CLAUDE.md 硬紅線）。
本機開發從 `.env` 讀取（不進 git），生產環境從 GCP Secret Manager 掛載。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _bool_env(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- 執行模式 ---
    DEBUG: bool = _bool_env("DEBUG", False)

    # --- GCP ---
    GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")

    # --- Secret（對應 GCP Secret Manager 的 SF_* ）---
    SESSION_SECRET: str = os.getenv("SF_SESSION_SECRET", "")
    ADMIN_PASSWORD: str = os.getenv("SF_ADMIN_PASSWORD", "")
    OPENAI_API_KEY: str = os.getenv("SF_OPENAI_API_KEY", "")
    CRAWLER_CREDENTIAL: Optional[str] = os.getenv("SF_CRAWLER_CREDENTIAL")


settings = Settings()

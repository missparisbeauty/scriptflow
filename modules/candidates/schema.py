"""candidates 模組 request / response schema — Phase 5 + 手動補爆款 5/2026。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


# GET /api/v1/candidates 用 query params（FastAPI Query），不需要 BaseModel
# 此處保留 schema 檔以對齊 rule-backend 的 schema.py 慣例
Strategy = Literal["balanced", "hotness"]

Platform = Literal["douyin", "xiaohongshu", "threads"]


class ManualCandidateRequest(BaseModel):
    """手動新增爆款（給 POST /api/v1/candidates/manual）。

    使用情境：Apify 爬不到（額度用完、平台不支援）時，使用者自己貼網址。
    """

    platform: Platform
    category: str = Field(..., min_length=1, max_length=20)
    title: str = Field(..., min_length=1, max_length=200)
    url: HttpUrl
    engagement: int = Field(0, ge=0, le=10_000_000_000)

"""candidates 模組 request / response schema — Phase 5。"""

from __future__ import annotations

from typing import Literal


# GET /api/v1/candidates 用 query params（FastAPI Query），不需要 BaseModel
# 此處保留 schema 檔以對齊 rule-backend 的 schema.py 慣例
Strategy = Literal["balanced", "hotness"]

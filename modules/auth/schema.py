"""auth 模組 request / response schema — Phase 5。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)

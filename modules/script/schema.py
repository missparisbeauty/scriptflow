"""script 模組 request schema — Phase 5。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    candidate_ids: list[str] = Field(..., min_length=1, max_length=10)
    category: str = Field(..., min_length=1, max_length=20)

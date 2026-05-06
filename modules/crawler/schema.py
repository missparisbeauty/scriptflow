"""crawler 模組 request schema — Phase 5。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TriggerRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=20)
    strategy: Literal["balanced", "hotness"] = "balanced"
    hours: int = Field(24, ge=1, le=168)

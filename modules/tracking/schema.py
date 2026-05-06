"""tracking 模組 request schema — Phase 5。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class TrackingRequest(BaseModel):
    script_id: str = Field(..., min_length=1, max_length=80)
    platform: str = Field(..., min_length=1, max_length=30)
    publish_url: HttpUrl


class MetricsUpdateRequest(BaseModel):
    metrics_field: Literal["metrics_7d", "metrics_14d"]
    metrics: dict = Field(..., max_length=20)

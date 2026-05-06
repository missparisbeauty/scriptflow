"""script 模組 request schema — Phase 5。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ScriptTypeLiteral = Literal["traffic", "trust", "harvest"]


class GenerateRequest(BaseModel):
    candidate_ids: list[str] = Field(..., min_length=1, max_length=10)
    category: str = Field(..., min_length=1, max_length=20)
    # 脆腳本類型：流量 / 知識信任 / 變現（僅影響 threads_reel）
    script_type: ScriptTypeLiteral = "traffic"

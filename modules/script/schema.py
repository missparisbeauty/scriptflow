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
    # 選定特定 item index（0~9）→ 只用這篇生成；不傳 = 用 doc 內全部 items
    selected_item_index: int | None = Field(None, ge=0, le=9)

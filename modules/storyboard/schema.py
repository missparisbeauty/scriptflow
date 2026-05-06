"""storyboard 模組 request schema — Phase 5。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PlatformLiteral = Literal["threads_reel", "ig_reels"]
ExportFormatLiteral = Literal["pdf", "word"]


class GenerateRequest(BaseModel):
    script_id: str = Field(..., min_length=1, max_length=80)
    platform: PlatformLiteral

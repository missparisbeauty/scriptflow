"""候選爆款 API route — Phase 5。

GET /api/v1/candidates?category={...}&strategy={balanced|hotness}
  需要登入；錯誤碼：CANDIDATES_NOT_READY（409）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from domain.responses import ok
from modules.auth.middleware import require_session
from modules.candidates.schema import Strategy
from modules.candidates.service import get_today_candidates

router = APIRouter(
    prefix="/api/v1/candidates",
    tags=["candidates"],
    dependencies=[Depends(require_session)],
)


@router.get("")
def list_today(
    strategy: Strategy = Query("balanced"),
    category: str | None = Query(None, max_length=20),
) -> dict:
    data = get_today_candidates(strategy=strategy, category=category)
    return ok(data)

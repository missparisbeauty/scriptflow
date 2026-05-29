"""候選爆款 API route — Phase 5 + 手動補爆款 5/2026。

GET  /api/v1/candidates?category={...}&strategy={balanced|hotness}
  需要登入；錯誤碼：CANDIDATES_NOT_READY（409）
GET  /api/v1/candidates/recent?days=5&category={...}
  取最近 N 天的候選，依日期由近到遠
POST /api/v1/candidates/manual
  手動新增一筆爆款到今日 candidate doc（Apify 額度用完時用）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from domain.responses import ok
from modules.auth.middleware import require_session
from modules.candidates.schema import ManualCandidateRequest, Strategy
from modules.candidates.service import (
    add_manual_candidate,
    get_recent_candidates,
    get_today_candidates,
    get_xhs_preview,
)

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


@router.get("/recent")
def list_recent(
    days: int = Query(5, ge=1, le=30),
    category: str | None = Query(None, max_length=20),
    strategy: Strategy = Query("balanced"),
) -> dict:
    data = get_recent_candidates(days=days, category=category, strategy=strategy)
    return ok(data)


@router.get("/xhs-preview")
def xhs_preview_endpoint(url: str = Query(..., max_length=600)) -> dict:
    """透過 Apify proxy 抓取小紅書貼文內容，供前端彈窗預覽。

    台灣 IP 無法直接存取小紅書（TCP 封鎖），改由後端 Apify 代理。
    每次呼叫消耗約 $0.010（zhorex actor）。
    """
    data = get_xhs_preview(url)
    return ok(data)


@router.post("/manual")
def manual_add(req: ManualCandidateRequest) -> dict:
    data = add_manual_candidate(
        platform=req.platform,
        category=req.category,
        title=req.title,
        url=str(req.url),
        engagement=req.engagement,
    )
    return ok(data)

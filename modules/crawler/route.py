"""手動觸發爬取 route — Phase 5。

POST /api/v1/crawler/trigger
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from domain.responses import ok
from modules.auth.middleware import require_session
from modules.crawler.schema import TriggerRequest
from modules.crawler.service import run_daily_crawl

router = APIRouter(
    prefix="/api/v1/crawler",
    tags=["crawler"],
    dependencies=[Depends(require_session)],
)


@router.post("/trigger")
def trigger(req: TriggerRequest) -> dict:
    data = run_daily_crawl(
        req.category,
        strategy=req.strategy,
        hours=req.hours,
    )
    return ok(data)

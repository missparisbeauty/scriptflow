"""成效追蹤 route — Phase 5。

POST /api/v1/tracking                       新增發布連結
GET  /api/v1/tracking/{id}/metrics          取得 7d/14d 指標
POST /api/v1/tracking/{id}/metrics          手動更新指標（spec F5）
POST /api/v1/tracking/{id}/feedback         AI 看數據給優化建議
GET  /api/v1/tracking/dna                   品牌爆款 DNA（spec F6）

錯誤碼：INSUFFICIENT_DATA（409）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from domain.responses import ok
from modules.auth.middleware import require_session
from modules.tracking.schema import MetricsUpdateRequest, TrackingRequest
from modules.tracking.service import (
    analyze_feedback,
    compute_dna,
    get_metrics,
    save_tracking,
    update_metrics,
)

router = APIRouter(
    prefix="/api/v1/tracking",
    tags=["tracking"],
    dependencies=[Depends(require_session)],
)


@router.post("")
def create_tracking(req: TrackingRequest) -> dict:
    tracking_id = save_tracking(
        req.script_id, req.platform, str(req.publish_url)
    )
    return ok({"tracking_id": tracking_id})


@router.get("/dna")
def dna() -> dict:
    return ok(compute_dna())


@router.get("/{tracking_id}/metrics")
def metrics_get(
    tracking_id: str = Path(..., min_length=3, max_length=80),
) -> dict:
    return ok(get_metrics(tracking_id))


@router.post("/{tracking_id}/metrics")
def metrics_update(
    req: MetricsUpdateRequest,
    tracking_id: str = Path(..., min_length=3, max_length=80),
) -> dict:
    update_metrics(
        tracking_id,
        metrics_field=req.metrics_field,
        metrics=req.metrics,
    )
    return ok({"tracking_id": tracking_id, "field": req.metrics_field})


@router.post("/{tracking_id}/feedback")
def feedback(
    tracking_id: str = Path(..., min_length=3, max_length=80),
) -> dict:
    """AI 看 7d/14d 成效給腳本優化建議（無 body，純讀 tracking + script）。"""
    return ok(analyze_feedback(tracking_id))

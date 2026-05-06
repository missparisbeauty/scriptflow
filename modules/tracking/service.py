"""TrackingService — Phase 4。

職責（spec-developer F5, F6）：
  - 儲存發布連結（save_tracking）
  - 更新 7d / 14d 成效（update_metrics）
  - 計算品牌爆款 DNA（compute_dna）
    * 樣本 < 5 → InsufficientData（前端顯示「需更多作品」）
    * 透過 ScriptService.get_script 取對應腳本，符合 rule-module-isolation

owner collection：tracking + brand_dna
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from domain.exceptions import InsufficientData, InvalidInput, ResourceNotFound
from infra import firestore as fs, llm_client
from modules.script import service as script_service

logger = logging.getLogger(__name__)

DNA_MIN_SAMPLES = 5  # 對齊 llm_client.DNA_MIN_SAMPLES 與 spec F6
DNA_MAX_FETCH = 200
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


# --- 對外 ---


def save_tracking(script_id: str, platform: str, publish_url: str) -> str:
    """新增發布連結。

    Returns:
        tracking_id
    """
    if not script_id:
        raise InvalidInput("script_id required")
    if not platform:
        raise InvalidInput("platform required")
    if not publish_url or not _URL_RE.match(publish_url):
        raise InvalidInput(
            "publish_url must start with http:// or https://"
        )

    tracking_id = f"tracking_{uuid.uuid4().hex[:10]}"
    fs.save_tracking(
        tracking_id,
        {
            "script_id": script_id,
            "platform": platform,
            "publish_url": publish_url,
            "metrics_7d": None,
            "metrics_14d": None,
        },
    )
    logger.info(
        "tracking.saved id=%s script=%s platform=%s",
        tracking_id,
        script_id,
        platform,
    )
    return tracking_id


def get_metrics(tracking_id: str) -> dict:
    """取一筆 tracking 的成效（含 7d / 14d）。"""
    doc = fs.get_tracking(tracking_id)
    if not doc:
        raise ResourceNotFound(
            f"tracking not found: {tracking_id}",
            tracking_id=tracking_id,
        )
    return {
        "tracking_id": tracking_id,
        "script_id": doc.get("script_id"),
        "platform": doc.get("platform"),
        "metrics_7d": doc.get("metrics_7d"),
        "metrics_14d": doc.get("metrics_14d"),
    }


def update_metrics(
    tracking_id: str,
    *,
    metrics_field: str,
    metrics: dict,
) -> None:
    """手動更新 7d / 14d metrics。"""
    if metrics_field not in {"metrics_7d", "metrics_14d"}:
        raise InvalidInput(
            "metrics_field must be metrics_7d or metrics_14d"
        )
    # fs 層也會驗一次（雙保險）
    fs.update_tracking_metrics(
        tracking_id,
        metrics_field=metrics_field,
        metrics=metrics,
    )


def compute_dna() -> dict:
    """聚合所有有 metrics 的 tracking，計算品牌爆款 DNA。

    完成條件：TrackingService.compute_dna()
              → DNA 結構（樣本不足回 INSUFFICIENT_DATA）
    """
    trackings = fs.list_tracking_recent(limit=DNA_MAX_FETCH)

    samples: list[dict] = []
    for t in trackings:
        if not t.get("metrics_7d"):
            continue  # 還沒收成效
        # 跨模組讀 scripts → 走 ScriptService（rule-module-isolation）
        script = script_service.get_script(t.get("script_id", ""))
        if not script:
            continue
        samples.append({"tracking": t, "script": script})

    if len(samples) < DNA_MIN_SAMPLES:
        raise InsufficientData(
            f"need >= {DNA_MIN_SAMPLES} samples with metrics_7d, "
            f"got {len(samples)}",
            sample_count=len(samples),
        )

    try:
        dna = llm_client.compute_dna(samples)
    except ValueError as e:
        # llm_client 也會驗 5 筆下限（雙保險）
        raise InsufficientData(str(e)) from e

    dna_id = (
        "dna_"
        + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    )
    payload = {**dna, "sample_count": len(samples)}
    fs.save_brand_dna(dna_id, payload)
    logger.info("dna.computed id=%s samples=%d", dna_id, len(samples))
    return {"id": dna_id, **payload}

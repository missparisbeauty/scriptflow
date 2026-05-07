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

from domain import prompts
from domain.exceptions import InsufficientData, InvalidInput, ResourceNotFound
from infra import firestore as fs, llm_client
from modules.script import service as script_service

_PLATFORM_LABEL = {
    "threads_post": "Threads 純文字",
    "threads_reel": "脆 30 秒",
    "ig_reels": "IG Reels 60 秒",
}

_METRIC_LABEL = {
    "views": "觀看數",
    "likes": "按讚",
    "comments": "留言",
    "shares": "分享",
    "saves": "收藏",
    "story_link_clicks": "連結點擊",
    "completion_rate": "完看率",
    "ctr": "CTR",
}

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


def analyze_feedback(tracking_id: str) -> dict:
    """根據 tracking 的成效 + 腳本內容，請 LLM 給優化建議。

    Returns:
        {"tracking_id": ..., "analysis": "...（純文字）"}

    Raises:
        ResourceNotFound: tracking_id 不存在
        InsufficientData: tracking 還沒填任何成效數據
    """
    doc = fs.get_tracking(tracking_id)
    if not doc:
        raise ResourceNotFound(
            f"tracking not found: {tracking_id}",
            tracking_id=tracking_id,
        )

    metrics_7d = doc.get("metrics_7d") or {}
    metrics_14d = doc.get("metrics_14d") or {}
    if not metrics_7d and not metrics_14d:
        raise InsufficientData(
            "no metrics filled yet — fill metrics_7d or metrics_14d first",
            sample_count=0,
        )

    # 取對應腳本（跨模組走 ScriptService 公開函式）
    script = script_service.get_script(doc.get("script_id", ""))
    if not script:
        raise ResourceNotFound(
            f"script not found for tracking {tracking_id}",
            tracking_id=tracking_id,
        )

    platform = doc.get("platform", "")
    platform_label = _PLATFORM_LABEL.get(platform, platform)

    # 抽腳本對應 platform 那版的內容（節錄前 600 字避免超 token）
    version = script.get(platform) or {}
    script_excerpt = _extract_script_excerpt(version)[:600]

    # 組數據區塊
    metrics_block = _format_metrics_block(metrics_7d, metrics_14d)

    sys_prompt = prompts.build_feedback_system_prompt()
    user_prompt = prompts.build_feedback_user_prompt(
        platform_label=platform_label,
        script_type=script.get("script_type") or "(未指定)",
        topic=script.get("topic") or "",
        category=script.get("category") or "",
        script_excerpt=script_excerpt,
        metrics_block=metrics_block,
    )

    # 不指定 response_format → 純文字輸出
    text = llm_client.generate_script(
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
    )
    logger.info(
        "tracking.feedback id=%s script=%s len=%d",
        tracking_id,
        doc.get("script_id"),
        len(text or ""),
    )
    return {
        "tracking_id": tracking_id,
        "script_id": doc.get("script_id"),
        "platform": platform,
        "analysis": text or "",
    }


def _extract_script_excerpt(version: dict) -> str:
    """從 script version 抽出可讀文字摘要。"""
    parts: list[str] = []
    if (c := version.get("content")):
        parts.append(c)
    for seg in version.get("segments", []) or []:
        time = seg.get("time", "")
        scene = seg.get("scene") or ""
        vo = seg.get("voiceover") or ""
        if scene or vo:
            parts.append(f"[{time}] 畫面：{scene}｜口白：{vo}")
    if (cap := version.get("caption")):
        parts.append(f"caption：{cap}")
    for cta in version.get("cta_variants", []) or []:
        if (t := cta.get("text")):
            parts.append(f"CTA[{cta.get('type','?')}]：{t}")
    return "\n".join(parts)


def _format_metrics_block(metrics_7d: dict, metrics_14d: dict) -> str:
    """把 7d / 14d 數據格式化成可讀文字。"""
    lines: list[str] = []
    for window_label, m in (("發布後 7 天", metrics_7d), ("發布後 14 天", metrics_14d)):
        if not m:
            continue
        lines.append(f"【{window_label}】")
        for k, v in m.items():
            label = _METRIC_LABEL.get(k, k)
            lines.append(f"  - {label}：{v}")
    return "\n".join(lines)


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

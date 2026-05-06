"""ScriptService — Phase 4。

職責（spec-developer F3）：
  - 從三個候選萃取流量節奏
  - 呼叫 OpenAI 文字 API 產三版本腳本（threads_post / threads_reel / ig_reels）
  - 執行合規掃描（domain.compliance_rules）
  - 產生 CTA 三變體（由 LLM 完成，這裡只驗證結構）
  - 寫入 scripts collection（owner module）

對外公開（給 Storyboard / Tracking 跨模組用）：
  - get_script(script_id) → dict | None
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from domain import categories, compliance_rules, prompts
from domain.exceptions import (
    InvalidInput,
    ScriptGenerationFailed,
)
from infra import firestore as fs, llm_client
from modules.candidates import service as candidates_service

logger = logging.getLogger(__name__)

# 三版本 → 合規掃描所用的 platform key
_COMPLIANCE_PLATFORM = {
    "threads_post": "threads",
    "threads_reel": "threads",
    "ig_reels": "xiaohongshu",  # IG 慣例採偏嚴標準
}


# --- 對外（route 用） ---


def generate(candidate_ids: list[str], category: str) -> dict:
    """生成三版本腳本。

    完成條件：ScriptService.generate([id1,id2,id3], '髮品')
              → threads_post / threads_reel / ig_reels + CTA + 合規
    """
    if not candidate_ids:
        raise InvalidInput("candidate_ids cannot be empty")
    if not categories.is_valid_category(category):
        raise InvalidInput(f"invalid category: {category}")

    docs = candidates_service.get_candidates(candidate_ids)
    if not docs:
        raise InvalidInput(
            f"no candidates found for ids: {candidate_ids}",
            candidate_ids=candidate_ids,
        )

    topic = _pick_topic(docs)
    summary = _build_candidates_summary(docs)
    system_prompt = prompts.build_system_prompt(
        category=category, topic=topic
    )

    # 三版本各呼叫一次 LLM
    versions: dict[str, dict] = {}
    for tpl in ("threads_post", "threads_reel", "ig_reels"):
        versions[tpl] = _generate_one_version(
            tpl,
            system_prompt=system_prompt,
            category=category,
            topic=topic,
            summary=summary,
        )

    # 寫入 scripts collection
    today = datetime.now(timezone.utc).date().isoformat()
    script_id = f"script_{today.replace('-', '')}_{uuid.uuid4().hex[:6]}"
    data = {
        "date": today,
        "category": category,
        "topic": topic,
        "source_candidate_ids": candidate_ids,
        **versions,
    }
    fs.save_script(script_id, data)
    logger.info(
        "script.generated id=%s category=%s topic=%s",
        script_id,
        category,
        topic[:20],
    )
    return {"script_id": script_id, **data}


def get_script(script_id: str) -> dict | None:
    """跨模組公開介面（StoryboardService / TrackingService 透過此函式取 script）。"""
    return fs.get_script(script_id)


# --- 內部 ---


def _generate_one_version(
    template_key: str,
    *,
    system_prompt: str,
    category: str,
    topic: str,
    summary: str,
) -> dict:
    """單一版本：build prompt → call LLM → parse → 合規掃描。"""
    user_prompt = prompts.build_prompt(
        template_key,
        category=category,
        topic=topic,
        candidates_summary=summary,
    )
    try:
        raw = llm_client.generate_script(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
        )
    except RuntimeError as e:
        # llm_client 三次重試後仍失敗
        raise ScriptGenerationFailed(
            f"LLM call failed for {template_key}",
            template=template_key,
            cause=str(e),
        ) from e

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ScriptGenerationFailed(
            f"LLM returned non-JSON for {template_key}",
            template=template_key,
        ) from e

    # 合規掃描
    text = _extract_text(parsed)
    parsed["compliance"] = compliance_rules.scan(
        text, _COMPLIANCE_PLATFORM[template_key]
    )
    return parsed


def _pick_topic(docs: list[dict]) -> str:
    """從 candidates 文件挑出主題。"""
    for d in docs:
        if d.get("topic"):
            return d["topic"]
    # 退而求其次：取第一個 item title 前 30 字
    for d in docs:
        items = d.get("items") or []
        if items:
            t = (items[0].get("title") or "")[:30]
            if t:
                return t
    return ""


def _build_candidates_summary(docs: list[dict]) -> str:
    """組可讀摘要給 LLM prompt（list 前 3 筆 items）。"""
    lines: list[str] = []
    for d in docs:
        for item in (d.get("items") or [])[:3]:
            lines.append(
                f"- [{item.get('platform','?')}] "
                f"{item.get('title','')} "
                f"(engagement={item.get('engagement', 0):,}, "
                f"funnel={item.get('funnel_role','?')})"
            )
    return "\n".join(lines) if lines else "(no candidates)"


def _extract_text(parsed: dict) -> str:
    """從解析後的 JSON 抽出所有可掃描文字。"""
    parts: list[str] = []
    if (c := parsed.get("content")):
        parts.append(c)
    for seg in parsed.get("segments", []):
        for k in ("scene", "voiceover", "caption_overlay"):
            if (v := seg.get(k)):
                parts.append(v)
    if (cap := parsed.get("caption")):
        parts.append(cap)
    for cta in parsed.get("cta_variants", []):
        if (t := cta.get("text")):
            parts.append(t)
    return "\n".join(parts)

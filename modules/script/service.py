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
import re
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


VALID_SCRIPT_TYPES = ("traffic", "trust", "harvest")


def generate(
    candidate_ids: list[str],
    category: str,
    *,
    script_type: str = "traffic",
    selected_item_index: int | None = None,
) -> dict:
    """生成三版本腳本。

    Args:
        candidate_ids: 候選 ID 清單
        category: 分類名稱（美妝 / 美食 / 髮品）
        script_type: 脆腳本類型 — traffic（流量）/ trust（知識信任）/ harvest（變現）
                     僅影響 threads_reel 版本（用 MissParis 品牌特化樣板）；
                     threads_post 與 ig_reels 仍使用通用樣板。

    完成條件：ScriptService.generate([id1,id2,id3], '髮品', script_type='traffic')
              → threads_post / threads_reel / ig_reels + CTA + 合規
    """
    if not candidate_ids:
        raise InvalidInput("candidate_ids cannot be empty")
    if not categories.is_valid_category(category):
        raise InvalidInput(f"invalid category: {category}")
    if script_type not in VALID_SCRIPT_TYPES:
        raise InvalidInput(
            f"script_type must be one of {VALID_SCRIPT_TYPES}, got {script_type!r}"
        )

    docs = candidates_service.get_candidates(candidate_ids)
    if not docs:
        raise InvalidInput(
            f"no candidates found for ids: {candidate_ids}",
            candidate_ids=candidate_ids,
        )

    # 選定特定 item → 把 doc.items 過濾到只剩那一篇
    if selected_item_index is not None:
        for doc in docs:
            items = doc.get("items") or []
            if 0 <= selected_item_index < len(items):
                doc["items"] = [items[selected_item_index]]
        # 過濾後可能某些 doc 沒 items，移除
        docs = [d for d in docs if d.get("items")]
        if not docs:
            raise InvalidInput(
                f"selected_item_index={selected_item_index} out of range",
                candidate_ids=candidate_ids,
            )

    topic = _pick_topic(docs)
    summary = _build_candidates_summary(docs)
    # MissParis 品牌特化 system prompt（含 4 角色設定）
    system_prompt = prompts.build_system_prompt(
        category=category, topic=topic, brand="missparis"
    )

    # 三版本各呼叫一次 LLM；threads_reel 走 MissParis 三類型樣板
    versions: dict[str, dict] = {}
    for tpl in ("threads_post", "threads_reel", "ig_reels"):
        actual_template_key = (
            f"threads_reel:{script_type}" if tpl == "threads_reel" else tpl
        )
        versions[tpl] = _generate_one_version(
            actual_template_key,
            system_prompt=system_prompt,
            category=category,
            topic=topic,
            summary=summary,
            output_key=tpl,
        )

    # 寫入 scripts collection
    today = datetime.now(timezone.utc).date().isoformat()
    script_id = f"script_{today.replace('-', '')}_{uuid.uuid4().hex[:6]}"
    data = {
        "date": today,
        "category": category,
        "topic": topic,
        "script_type": script_type,
        "source_candidate_ids": candidate_ids,
        **versions,
    }
    fs.save_script(script_id, data)
    logger.info(
        "script.generated id=%s category=%s type=%s topic=%s",
        script_id,
        category,
        script_type,
        topic[:20],
    )
    return {"script_id": script_id, **data}


def get_script(script_id: str) -> dict | None:
    """跨模組公開介面（StoryboardService / TrackingService 透過此函式取 script）。"""
    return fs.get_script(script_id)


def get_latest_script() -> dict | None:
    """拉最近一次生成的腳本（沒有任何腳本回 None）。

    主要用途：LLM 生成完成但前端連線斷掉時的救援機制。
    """
    recent = fs.list_recent_scripts(limit=1)
    return recent[0] if recent else None


# --- 內部 ---


def _generate_one_version(
    template_key: str,
    *,
    system_prompt: str,
    category: str,
    topic: str,
    summary: str,
    output_key: str,
) -> dict:
    """單一版本：build prompt → call LLM → parse → 合規掃描。

    Args:
        template_key: 樣板鍵（含 ':variant' 後綴時走 MissParis 特化版）
        output_key: 對應前端輸出鍵（threads_post / threads_reel / ig_reels）
    """
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
        parsed = _parse_llm_json(raw)
    except json.JSONDecodeError as e:
        logger.warning(
            "llm json parse failed template=%s raw_preview=%r",
            template_key,
            (raw or "")[:200],
        )
        raise ScriptGenerationFailed(
            f"LLM returned non-JSON for {template_key}",
            template=template_key,
        ) from e

    # 合規掃描（用 output_key 對應 platform）
    text = _extract_text(parsed)
    parsed["compliance"] = compliance_rules.scan(
        text, _COMPLIANCE_PLATFORM[output_key]
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


def _parse_llm_json(raw: str) -> dict:
    """LLM 偶爾會把 JSON 包在 markdown code fence 或前後加額外文字 — 容錯解析。

    解析順序：
      1. 直接 json.loads（最常見，response_format=json_object 通常 OK）
      2. 去掉 ```json ... ``` 或 ``` ... ``` 後再試
      3. regex 抓第一個平衡 {...} 區塊
    全部失敗則丟原 JSONDecodeError 給上層。
    """
    if not raw:
        raise json.JSONDecodeError("empty response", "", 0)

    # Step 1：直接解
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Step 2：去 markdown code fence
    cleaned = raw.strip()
    fence_match = re.match(
        r"^```(?:json)?\s*(.+?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE
    )
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Step 3：抓第一個 {...} 區塊（dotall）
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # 全失敗 → 拋原本錯誤訊息給上層 log
    raise json.JSONDecodeError(
        "LLM output not parseable as JSON after fence/brace cleanup",
        raw[:100],
        0,
    )


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

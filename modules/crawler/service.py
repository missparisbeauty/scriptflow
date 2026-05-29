"""CrawlerService — Phase 4。

職責（spec-developer F1）：
  - 協調三平台爬取（透過 infra/crawler_client）
  - 用 domain/rules 計算 topic_match / purchase_intent_density / funnel_role
  - 主題集中度（topic_concentration）= top 3 候選的相似度平均
  - 寫入 candidates collection（owner module）
  - 單一平台失敗不中斷其他

owner collection：candidates
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

from domain import categories, rules
from domain.exceptions import InvalidInput
from infra import crawler_client, firestore as fs


def _extract_note_id(url: str) -> str | None:
    """Extract hex note ID from a xiaohongshu.com explore URL."""
    m = re.search(r"/explore/([0-9a-f]{16,32})", url or "")
    return m.group(1) if m else None

logger = logging.getLogger(__name__)

VALID_STRATEGIES = ("balanced", "hotness")
DEFAULT_TOP_N = 3  # spec：每分類選 3 個候選


# --- 對外 ---


def run_daily_crawl(
    category: str,
    *,
    strategy: str = "balanced",
    hours: int = 24,
) -> dict:
    """每日爬取 + 篩選 + 寫入 candidates。

    完成條件：CrawlerService.run_daily_crawl('髮品') → 寫入 candidates collection
    """
    if not categories.is_valid_category(category):
        raise InvalidInput(f"invalid category: {category}")
    if strategy not in VALID_STRATEGIES:
        raise InvalidInput(f"strategy must be one of {VALID_STRATEGIES}")

    today = datetime.now(timezone.utc).date().isoformat()
    candidate_id = f"{today.replace('-', '')}_{category}"

    # 1. 三平台爬取（單一失敗不中斷）
    # limit=10：每平台只抓 10 筆，控制 Apify 月用量（從 30 降到 10）
    raw_items: list[dict] = []
    failed: list[str] = []
    for platform in crawler_client.list_supported_platforms():
        try:
            items = crawler_client.fetch_hot_content(
                platform, category, hours=hours, limit=10
            )
            raw_items.extend(items)
        except Exception as e:
            logger.warning(
                "crawler.platform_failed platform=%s err=%s",
                platform,
                type(e).__name__,
            )
            failed.append(platform)

    # 2. 非 mock 模式時，過濾掉各平台 fallback 的 mock 假資料
    #    （mock fixture 的互動數是假的高數字，若不過濾會壓過真實爬取結果）
    if not crawler_client.is_mock():
        real_items = [
            it for it in raw_items
            if "example.com" not in it.get("url", "")
        ]
        if real_items:  # 至少有一個真實平台有資料才替換，避免全空
            raw_items = real_items

    # 3. 對每筆計算 domain 指標
    enriched = [_enrich(item, category) for item in raw_items]
    enriched = _ensure_xhs_fallback(enriched, category)

    # 3. 排序並截 top N
    top = _select_top(enriched, strategy=strategy, n=DEFAULT_TOP_N)
    top = _force_xhs_slot(top, enriched, category, n=DEFAULT_TOP_N)
    for i, item in enumerate(top, start=1):
        item["rank"] = i

    # 4. 把 XHS 項目的 preview 存進獨立快取 collection，同時保留在 item。
    #    前端可直接用 item.preview 顯示，cache 則供舊頁面/重整後 API 讀取。
    for item in top:
        if item.get("platform") == "xiaohongshu":
            preview = item.get("preview")
            if preview:
                note_id = _extract_note_id(item.get("source_url", ""))
                if note_id:
                    try:
                        fs.save_xhs_preview_cache(note_id, preview)
                        logger.info("crawler.xhs_preview_cached note_id=%s", note_id)
                    except Exception as e:
                        logger.warning(
                            "crawler.xhs_preview_cache_failed note_id=%s err=%s",
                            note_id, type(e).__name__,
                        )

    # 6. 全平台都沒結果 → 不存空 doc 污染日曆（2026-05 改）
    if not top:
        logger.warning(
            "crawler.no_items_skipped category=%s failed_platforms=%s",
            category,
            failed,
        )
        return {
            "candidate_id": None,
            "date": today,
            "category": category,
            "items": [],
            "failed_platforms": failed,
            "skipped": True,
        }

    # 7. 主題與集中度
    topic, concentration = _summarize_topic(top)

    # 8. 寫入 candidates collection
    data = {
        "date": today,
        "category": category,
        "topic": topic,
        "topic_concentration": round(concentration, 3),
        "strategy": strategy,
        "items": top,
        "failed_platforms": failed,
    }
    fs.save_candidate(candidate_id, data)
    logger.info(
        "crawler.done category=%s items=%d failed=%s",
        category,
        len(top),
        failed,
    )

    return {"candidate_id": candidate_id, **data}


# --- 內部 helper ---


def _enrich(item: dict, category: str) -> dict:
    """補上 topic_match / purchase_intent_density / funnel_role。"""
    title = item.get("title", "") or ""
    item["topic_match"] = round(
        rules.compute_similarity(title, category), 3
    )
    item["purchase_intent_density"] = round(
        rules.compute_purchase_intent_density(title), 3
    )
    item["funnel_role"] = _classify_role(item)
    return item


def _ensure_xhs_fallback(items: list[dict], category: str) -> list[dict]:
    """Force one XHS slot even when the XHS actor returns no usable rows."""
    if any(item.get("platform") == "xiaohongshu" for item in items):
        return items

    try:
        fallback_items = crawler_client._mock_fetch_hot_content(
            "xiaohongshu", category, hours=24, limit=1
        )
    except Exception as e:
        logger.warning(
            "crawler.xhs_forced_fallback_failed category=%s err=%s",
            category, type(e).__name__,
        )
        return items

    if not fallback_items:
        return items

    fallback = dict(fallback_items[0])
    keyword = f"{category} {fallback.get('title', '')}".strip()
    search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}"
    fallback["url"] = search_url
    fallback["source_url"] = search_url
    fallback["search_keyword"] = keyword
    fallback["is_fallback"] = True
    fallback["fallback_reason"] = "xiaohongshu_actor_empty"
    fallback["engagement"] = 0
    logger.warning("crawler.xhs_forced_fallback category=%s", category)
    return [*items, _enrich(fallback, category)]


def _force_xhs_slot(
    top: list[dict],
    enriched: list[dict],
    category: str,
    *,
    n: int,
) -> list[dict]:
    """Final guard: top candidates must contain one XHS item."""
    if any(item.get("platform") == "xiaohongshu" for item in top):
        return top

    with_xhs = _ensure_xhs_fallback(enriched, category)
    xhs_item = next(
        (item for item in with_xhs if item.get("platform") == "xiaohongshu"),
        None,
    )
    if xhs_item is None:
        return top

    if len(top) < n:
        return [*top, xhs_item]
    return [*top[: max(n - 1, 0)], xhs_item]


def _classify_role(item: dict) -> str:
    """5 階段漏斗角色推斷（購買決策旅程）。

    判斷順序（先比強訊號）：
      1. purchase_intent ≥ 0.10  → decision    （決策，強烈購買訊號）
      2. topic_match ≥ 0.10
         + intent ≥ 0.05         → brand_value （看見品牌價值）
         + intent < 0.05         → evaluation  （評估比價）
      3. topic_match ≥ 0.05      → interest    （興趣）
      4. 以上皆否                → awareness   （認知）

    門檻定義在 domain/rules.py，調整門檻不需改本函式。
    """
    intent = item.get("purchase_intent_density", 0)
    topic = item.get("topic_match", 0)

    if intent >= rules.PURCHASE_INTENT_DECISION_THRESHOLD:
        return "decision"
    if topic >= rules.TOPIC_MATCH_EVALUATION_THRESHOLD:
        if intent >= rules.PURCHASE_INTENT_BRAND_THRESHOLD:
            return "brand_value"
        return "evaluation"
    if topic >= rules.TOPIC_MATCH_INTEREST_THRESHOLD:
        return "interest"
    return "awareness"


def _select_top(items: list[dict], *, strategy: str, n: int) -> list[dict]:
    """依策略排序取 top N。"""
    if strategy == "hotness":
        key = lambda x: x.get("engagement", 0)
    else:  # balanced
        # 平衡 engagement 與 topic_match
        def key(x: dict) -> float:
            return float(
                x.get("engagement", 0) * (0.5 + x.get("topic_match", 0))
            )
    ranked = sorted(items, key=key, reverse=True)
    if n <= 1:
        return ranked[:n]

    selected: list[dict] = []

    # XHS is strategically important for this product. Douyin/TikTok often has
    # much larger engagement numbers, so preserve one XHS item when available.
    best_xhs = next(
        (item for item in ranked if item.get("platform") == "xiaohongshu"),
        None,
    )
    if best_xhs is not None:
        selected.append(best_xhs)

    for item in ranked:
        if len(selected) >= n:
            break
        if item not in selected:
            selected.append(item)

    return sorted(selected, key=key, reverse=True)[:n]


def _summarize_topic(top: list[dict]) -> tuple[str, float]:
    """主題（取首位 title 前 30 字）+ 集中度（topic_match 平均）。"""
    if not top:
        return "", 0.0
    topic = (top[0].get("title") or "")[:30]
    avg = sum(it.get("topic_match", 0) for it in top) / len(top)
    return topic, avg

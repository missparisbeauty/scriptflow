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
from datetime import datetime, timezone

from domain import categories, rules
from domain.exceptions import InvalidInput
from infra import crawler_client, firestore as fs

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
    raw_items: list[dict] = []
    failed: list[str] = []
    for platform in crawler_client.list_supported_platforms():
        try:
            items = crawler_client.fetch_hot_content(
                platform, category, hours=hours
            )
            raw_items.extend(items)
        except Exception as e:
            logger.warning(
                "crawler.platform_failed platform=%s err=%s",
                platform,
                type(e).__name__,
            )
            failed.append(platform)

    # 2. 對每筆計算 domain 指標
    enriched = [_enrich(item, category) for item in raw_items]

    # 3. 排序並截 top N
    top = _select_top(enriched, strategy=strategy, n=DEFAULT_TOP_N)
    for i, item in enumerate(top, start=1):
        item["rank"] = i

    # 4. 主題與集中度
    topic, concentration = _summarize_topic(top)

    # 5. 寫入 candidates collection
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


def _classify_role(item: dict) -> str:
    """簡易漏斗角色推斷（Phase 7 可優化）。"""
    if (
        item.get("purchase_intent_density", 0)
        >= rules.PURCHASE_INTENT_HARVEST_THRESHOLD
    ):
        return "harvest"
    if item.get("topic_match", 0) >= 0.10:
        return "pull"
    return "seed"


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
    return sorted(items, key=key, reverse=True)[:n]


def _summarize_topic(top: list[dict]) -> tuple[str, float]:
    """主題（取首位 title 前 30 字）+ 集中度（topic_match 平均）。"""
    if not top:
        return "", 0.0
    topic = (top[0].get("title") or "")[:30]
    avg = sum(it.get("topic_match", 0) for it in top) / len(top)
    return topic, avg

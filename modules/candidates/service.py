"""CandidateService — Phase 4。

職責（spec-developer F2）：
  - 管理今日候選；依策略 (balanced/hotness) 篩選
  - 不負責爬取（CrawlerService 寫入 candidates collection）
  - 提供跨模組公開介面：get_candidates(ids) 給 ScriptService 用

owner collection：candidates
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain import categories
from domain.exceptions import CandidatesNotReady, InvalidInput
from infra import firestore as fs

VALID_STRATEGIES = ("balanced", "hotness")
MAX_RECENT_DAYS = 30  # 防呆：最多查 30 天


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _make_candidate_id(date: str, category: str) -> str:
    """yyyymmdd_category，與 CrawlerService 的寫入慣例一致。"""
    return f"{date.replace('-', '')}_{category}"


# --- 對外（route 用） ---


def get_today_candidates(
    strategy: str = "balanced",
    category: str | None = None,
) -> dict:
    """取今日候選清單。

    完成條件：CandidateService.get_today_candidates('balanced') → 3 個候選
    """
    if strategy not in VALID_STRATEGIES:
        raise InvalidInput(f"strategy must be one of {VALID_STRATEGIES}")

    today = _today_iso()

    if category is not None:
        if not categories.is_valid_category(category):
            raise InvalidInput(f"invalid category: {category}")
        doc = fs.get_candidate(_make_candidate_id(today, category))
        if not doc:
            raise CandidatesNotReady(
                f"no candidates for {category} on {today}",
                date=today,
                category=category,
            )
        # 過濾一下 strategy（單筆 candidate doc 已經是某 strategy）
        return doc

    # 沒指定分類 → 回今天所有分類
    docs = fs.list_candidates_by_date(today)
    if not docs:
        raise CandidatesNotReady(f"no candidates for {today}", date=today)
    return {"date": today, "items": docs}


def get_recent_candidates(
    *,
    days: int = 5,
    category: str | None = None,
    strategy: str = "balanced",
) -> dict:
    """取最近 N 天的候選（依日期由近到遠回傳）。

    Args:
        days: 1~30
        category: 限定分類；None = 所有分類
        strategy: "balanced" 或 "hotness"。會對每個 doc 內的 items 即時重排。

    Returns:
        {"days": N, "strategy": "...", "buckets": [
            {"date": "2026-05-07", "docs": [doc, doc, ...]},
            {"date": "2026-05-06", "docs": [...]},
            ...
        ]}
    """
    if not 1 <= days <= MAX_RECENT_DAYS:
        raise InvalidInput(f"days must be 1..{MAX_RECENT_DAYS}, got {days}")
    if strategy not in VALID_STRATEGIES:
        raise InvalidInput(f"strategy must be one of {VALID_STRATEGIES}")
    if category is not None and not categories.is_valid_category(category):
        raise InvalidInput(f"invalid category: {category}")

    today = datetime.now(timezone.utc).date()
    buckets: list[dict] = []
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        if category:
            doc = fs.get_candidate(_make_candidate_id(d, category))
            docs = [doc] if doc else []
        else:
            docs = fs.list_candidates_by_date(d)
        # 依策略對每個 doc 內的 items 即時重排（不寫回 Firestore）
        for doc in docs:
            if isinstance(doc.get("items"), list):
                doc["items"] = _resort_items(doc["items"], strategy=strategy)
        buckets.append({"date": d, "docs": docs})
    return {"days": days, "strategy": strategy, "buckets": buckets}


def _resort_items(items: list[dict], *, strategy: str) -> list[dict]:
    """依策略對 items 重排並補 rank。"""
    if strategy == "hotness":
        key = lambda x: x.get("engagement", 0) or 0
    else:  # balanced
        def key(x: dict) -> float:
            return float(
                (x.get("engagement", 0) or 0)
                * (0.5 + (x.get("topic_match", 0) or 0))
            )
    sorted_items = sorted(items, key=key, reverse=True)
    # 重新標 rank（1, 2, 3, ...）
    for i, it in enumerate(sorted_items, start=1):
        it["rank"] = i
    return sorted_items


# --- 跨模組公開（ScriptService 用） ---


def get_candidates(candidate_ids: list[str]) -> list[dict]:
    """依 ID 取得多筆候選 doc。

    Args:
        candidate_ids: 例 ['20260506_髮品']

    Returns:
        list of candidate doc，找不到的 ID 會被略過（不拋）。
    """
    out: list[dict] = []
    for cid in candidate_ids:
        doc = fs.get_candidate(cid)
        if doc:
            out.append(doc)
    return out

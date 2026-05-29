"""CandidateService — Phase 4。

職責（spec-developer F2）：
  - 管理今日候選；依策略 (balanced/hotness) 篩選
  - 不負責爬取（CrawlerService 寫入 candidates collection）
  - 提供跨模組公開介面：get_candidates(ids) 給 ScriptService 用

owner collection：candidates
"""

from __future__ import annotations

import re
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from domain import categories, rules
from domain.exceptions import CandidatesNotReady, InvalidInput, ResourceNotFound
from infra import crawler_client, firestore as fs

logger = logging.getLogger(__name__)

# SSRF 防護：只允許小紅書筆記 URL（explore/hex_id 格式）
_XHS_NOTE_URL_RE = re.compile(
    r"^https://www\.xiaohongshu\.com/explore/[0-9a-f]{18,24}$"
)
_XHS_NOTE_ID_RE = re.compile(r"^[0-9a-f]{18,24}$")
_XHS_ALLOWED_QUERY_KEYS = {"xsec_token", "xsec_source"}

SUPPORTED_MANUAL_PLATFORMS = ("douyin", "xiaohongshu")

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
        _ensure_xhs_candidate(doc)
        _hydrate_xhs_previews(doc)
        return doc

    # 沒指定分類 → 回今天所有分類
    docs = fs.list_candidates_by_date(today)
    if not docs:
        raise CandidatesNotReady(f"no candidates for {today}", date=today)
    for doc in docs:
        _ensure_xhs_candidate(doc)
        _hydrate_xhs_previews(doc)
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
            _ensure_xhs_candidate(doc)
            _hydrate_xhs_previews(doc)
            if isinstance(doc.get("items"), list):
                doc["items"] = _resort_items(doc["items"], strategy=strategy)
        buckets.append({"date": d, "docs": docs})
    return {"days": days, "strategy": strategy, "buckets": buckets}


def _hydrate_xhs_previews(doc: dict) -> None:
    """Attach cached XHS preview data to candidate items when available."""
    items = doc.get("items")
    if not isinstance(items, list):
        return

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("platform") != "xiaohongshu" or item.get("preview"):
            continue
        note_id = _extract_note_id(item.get("source_url") or item.get("url") or "")
        if not note_id:
            continue
        cached = fs.get_xhs_preview_cache(note_id)
        if _is_usable_xhs_preview(cached):
            item["preview"] = cached


def _ensure_xhs_candidate(doc: dict) -> None:
    """Add one XHS fallback item to older candidate docs that only contain Douyin."""
    items = doc.get("items")
    if not isinstance(items, list):
        return
    if any(isinstance(item, dict) and item.get("platform") == "xiaohongshu" for item in items):
        return

    category = doc.get("category")
    if not isinstance(category, str) or not category:
        return

    try:
        fallback_items = crawler_client._mock_fetch_hot_content(
            "xiaohongshu", category, hours=24, limit=1
        )
    except Exception:
        return
    if not fallback_items:
        return

    fallback = dict(fallback_items[0])
    keyword = f"{category} {fallback.get('title', '')}".strip()
    search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}"
    fallback["url"] = search_url
    fallback["source_url"] = search_url
    fallback["search_keyword"] = keyword
    fallback["engagement"] = 0
    fallback["is_fallback"] = True
    fallback["fallback_reason"] = "xiaohongshu_actor_empty"
    fallback["topic_match"] = round(rules.compute_similarity(fallback.get("title", ""), category), 3)
    fallback["purchase_intent_density"] = round(
        rules.compute_purchase_intent_density(fallback.get("title", "")), 3
    )
    fallback["funnel_role"] = _classify_role_inline(
        fallback["topic_match"], fallback["purchase_intent_density"]
    )
    display_limit = 3
    if len(items) >= display_limit:
        items[display_limit - 1] = fallback
        del items[display_limit:]
    else:
        items.append(fallback)

    for idx, item in enumerate(items, start=1):
        if isinstance(item, dict):
            item["rank"] = idx


def _resort_items(items: list[dict], *, strategy: str) -> list[dict]:
    """依策略對 items 重排並補 rank。"""
    def manual_boost(x: dict) -> int:
        return 1 if x.get("is_manual") else 0

    if strategy == "hotness":
        key = lambda x: (manual_boost(x), x.get("engagement", 0) or 0)
    else:  # balanced
        def key(x: dict) -> tuple[int, float]:
            return (
                manual_boost(x),
                float(
                    (x.get("engagement", 0) or 0)
                    * (0.5 + (x.get("topic_match", 0) or 0))
                ),
            )
    sorted_items = sorted(items, key=key, reverse=True)
    # 重新標 rank（1, 2, 3, ...）
    for i, it in enumerate(sorted_items, start=1):
        it["rank"] = i
    return sorted_items


def add_manual_candidate(
    *,
    platform: str,
    category: str,
    title: str,
    url: str,
    engagement: int = 0,
) -> dict:
    """手動新增一筆爆款到今日 candidate doc。

    使用情境：Apify 額度用完 / 找到爆款想直接加入候選池。
    若今日 doc 不存在 → 建立；存在 → append 到 items[]，標記 is_manual=True。

    Args:
        platform: 必須在 SUPPORTED_MANUAL_PLATFORMS 內
        category: 必須是合法分類
        title: 1-200 字
        url: http(s) URL（前端用 HttpUrl 已驗）
        engagement: 互動數，預設 0

    Returns:
        更新後的 candidate doc
    """
    if platform not in SUPPORTED_MANUAL_PLATFORMS:
        raise InvalidInput(
            f"platform must be one of {SUPPORTED_MANUAL_PLATFORMS}, got {platform!r}"
        )
    if not categories.is_valid_category(category):
        raise InvalidInput(f"invalid category: {category}")
    title = (title or "").strip()
    if not title:
        raise InvalidInput("title cannot be empty")
    url = str(url).strip()
    if platform == "xiaohongshu":
        clean_url = _sanitize_xhs_note_url(url)
        if clean_url is None:
            raise InvalidInput(
                "小紅書手動補爆款只接受 "
                "https://www.xiaohongshu.com/explore/<note_id> 原文連結"
            )
        url = clean_url

    today = _today_iso()
    doc_id = _make_candidate_id(today, category)
    doc = fs.get_candidate(doc_id)

    # 新 item — 用 domain.rules 計算 topic_match / intent / 角色（與 crawler 一致）
    topic_match = round(rules.compute_similarity(title, category), 3)
    intent = round(rules.compute_purchase_intent_density(title), 3)
    new_item = {
        "platform": platform,
        "url": url,
        "source_url": url,
        "title": title[:200],
        "engagement": int(engagement),
        "completion_rate": None,
        "topic_match": topic_match,
        "purchase_intent_density": intent,
        "funnel_role": _classify_role_inline(topic_match, intent),
        "b_track_similarity": None,
        "is_manual": True,
    }

    if doc is None:
        # 今日還沒爬過，建立一個新 doc 只含這筆 manual 條目
        doc = {
            "date": today,
            "category": category,
            "topic": title[:30],
            "topic_concentration": 0.0,
            "failed_platforms": [],
            "items": [new_item],
        }
    else:
        items = list(doc.get("items") or [])
        items.append(new_item)
        doc["items"] = items

    fs.save_candidate(doc_id, doc)
    return doc


def _classify_role_inline(topic: float, intent: float) -> str:
    """與 modules/crawler/service._classify_role 邏輯一致，
    這裡 inline 避免跨模組 import（rule-module-isolation）。
    判斷邏輯之後若要共用可移到 domain/rules.py。"""
    if intent >= rules.PURCHASE_INTENT_DECISION_THRESHOLD:
        return "decision"
    if topic >= rules.TOPIC_MATCH_EVALUATION_THRESHOLD:
        if intent >= rules.PURCHASE_INTENT_BRAND_THRESHOLD:
            return "brand_value"
        return "evaluation"
    if topic >= rules.TOPIC_MATCH_INTEREST_THRESHOLD:
        return "interest"
    return "awareness"


# --- 小紅書預覽（Apify proxy，台灣 IP 無法直連） ---


def _extract_note_id(url: str) -> str | None:
    """Extract hex note ID from a xiaohongshu.com explore URL."""
    m = re.search(r"/explore/([0-9a-f]{16,32})", url or "")
    return m.group(1) if m else None


def get_xhs_preview(note_url: str) -> dict:
    """取得小紅書貼文預覽，供後台彈窗顯示。

    優先順序：
      ① Firestore xhs_preview_cache（爬取時存入，0 延遲，100% 可靠）
      ② Apify 即時抓取（快取 miss 時嘗試，可能失敗）

    Args:
        note_url: xiaohongshu.com/explore/{hex_id} 格式（含 xsec_token 亦可）

    Returns:
        {"title", "content", "images", "author", "likes", "comments", "collects"}

    Raises:
        InvalidInput: URL 格式不符
        ResourceNotFound: 快取未命中且 Apify 也無資料
    """
    clean_url = _sanitize_xhs_note_url(note_url)
    if clean_url is None:
        raise InvalidInput(
            f"invalid xiaohongshu note url: {note_url!r}; "
            "only https://www.xiaohongshu.com/explore/<hex_id> is allowed"
        )

    # ① Firestore 快取（爬取時寫入，直接回傳）
    note_id = _extract_note_id(clean_url)
    if note_id:
        cached = fs.get_xhs_preview_cache(note_id)
        if _is_usable_xhs_preview(cached):
            return cached

    # ② Apify fallback（快取 miss 時，適用於舊候選或手動補入的 URL）
    result = crawler_client.fetch_xhs_post_details(clean_url)
    if result is None:
        raise ResourceNotFound(
            f"xhs post not found or preview unavailable: {clean_url}"
        )
    if note_id and _is_usable_xhs_preview(result):
        try:
            fs.save_xhs_preview_cache(note_id, result)
        except Exception as e:
            logger.warning(
                "xhs_preview_cache_save_failed note_id=%s err=%s",
                note_id, type(e).__name__,
            )
    return result


def _is_usable_xhs_preview(preview: dict | None) -> bool:
    """A cached preview is useful only if it has body text or media."""
    if not isinstance(preview, dict):
        return False
    content = (preview.get("content") or "").strip()
    images = preview.get("images")
    return bool(content or (isinstance(images, list) and images))


# --- 跨模組公開（ScriptService 用） ---


def _sanitize_xhs_note_url(note_url: str) -> str | None:
    """Allow only Xiaohongshu note URLs plus known-safe auth query params."""
    if _XHS_NOTE_URL_RE.match(note_url):
        return note_url

    try:
        parsed = urlsplit(note_url)
    except ValueError:
        return None

    if parsed.scheme != "https" or parsed.netloc != "www.xiaohongshu.com":
        return None

    # 接受兩種貼文路徑：
    #   /explore/{id}            （網頁版網址）
    #   /discovery/item/{id}     （App / pc 分享連結格式，自動轉成 explore）
    note_id = None
    for prefix in ("/explore/", "/discovery/item/"):
        if parsed.path.startswith(prefix):
            note_id = parsed.path[len(prefix):].strip("/")
            break
    if note_id is None or not _XHS_NOTE_ID_RE.fullmatch(note_id):
        return None

    kept_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key in _XHS_ALLOWED_QUERY_KEYS and value
    ]
    query = urlencode(kept_params)
    # 一律正規化成 /explore/ 格式（分享連結的 /discovery/item/ 也轉成 explore）
    return urlunsplit(("https", "www.xiaohongshu.com", f"/explore/{note_id}", query, ""))


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

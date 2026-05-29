"""雙平台爬取輔助 client 封裝 — Phase 3 + Apify + TikWM 整合。

責任：
  - fetch_hot_content(platform, category, hours, limit) → list[dict]
  - 雙平台：xiaohongshu / douyin
  - 介面對齊 candidates collection 的 items[*] 欄位（spec-developer）
  - 後端模式（CRAWLER_BACKEND env）：
      mock   → 回確定性測試資料
      tikwm  → 呼叫 tikwm.com 公開 API（免費，抖音/TikTok）
      apify  → 呼叫 Apify Actor API（需設 SF_APIFY_TOKEN）
      未設定  → 有 APIFY_TOKEN 走 apify，否則走 tikwm

設計：
  - tikwm 只支援 douyin；xiaohongshu 無 tikwm actor，fallback mock
  - douyin Apify 失敗時自動 fallback TikWM（免費備援）
  - Apify Actor IDs 透過 env 可覆寫，預設用 clockworks/free-tiktok-scraper
  - rule-ai-llm：API token 只在 infra 層讀取
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

# --- 設定 ---

SUPPORTED_PLATFORMS = ("xiaohongshu", "douyin")
APIFY_TIMEOUT_SECONDS = 90   # Apify run-sync 較慢
TIKWM_TIMEOUT_SECONDS = 30   # TikWM 直接 API，較快
MAX_HOURS = 168
MAX_LIMIT = 50

APIFY_BASE_URL = "https://api.apify.com/v2"
TIKWM_BASE_URL = "https://tikwm.com/api"

# 各平台對應的 Apify Actor ID（env 可覆寫）
APIFY_ACTOR_DOUYIN = os.getenv(
    "APIFY_ACTOR_DOUYIN", "clockworks/free-tiktok-scraper"
)
APIFY_ACTOR_XIAOHONGSHU = os.getenv(
    "APIFY_ACTOR_XIAOHONGSHU", "zhorex/rednote-xiaohongshu-scraper"
)
APIFY_ACTOR_XIAOHONGSHU_PREVIEW = os.getenv(
    "APIFY_ACTOR_XIAOHONGSHU_PREVIEW", "zhorex/rednote-xiaohongshu-scraper"
)
APIFY_ACTOR_THREADS = os.getenv("APIFY_ACTOR_THREADS", "")
XHS_COOKIES = os.getenv("SF_XHS_COOKIES", "")

# 各分類對應的搜尋關鍵字
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "髮品": ["髮膜", "護髮", "染髮"],
    "美妝": ["彩妝", "保養", "化妝品"],
    "美食": ["美食", "食譜", "便當"],
}

# --- 語言過濾（只留中文圈內容） ---
_CJK_RE = re.compile(r"[一-鿿]")
_JAPANESE_KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")
_KOREAN_RE = re.compile(r"[가-힯]")
_NON_LETTER_RE = re.compile(r"[\s\W\d#@_]+")


def _is_chinese_content(text: str) -> bool:
    if not text:
        return False
    if _JAPANESE_KANA_RE.search(text):
        return False
    if _KOREAN_RE.search(text):
        return False
    return bool(_CJK_RE.search(text))


# --- 後端路由 ---

def _resolve_backend() -> str:
    """決定本次爬取使用哪個後端。

    優先順序：
      1. CRAWLER_BACKEND env 明確指定 → 照用
      2. 未指定 + 有 APIFY_TOKEN → apify
      3. 未指定 + 無 APIFY_TOKEN → tikwm（免費，不降 mock）
    """
    backend = os.getenv("CRAWLER_BACKEND", "").lower()
    if backend in ("mock", "apify", "tikwm"):
        return backend
    # auto 模式
    return "apify" if settings.APIFY_TOKEN else "tikwm"


def is_mock() -> bool:
    """是否走 mock 模式（供前端 warning banner 判斷）。"""
    return _resolve_backend() == "mock"


def list_supported_platforms() -> list[str]:
    return list(SUPPORTED_PLATFORMS)


def fetch_hot_content(
    platform: str,
    category: str,
    *,
    hours: int = 24,
    limit: int = 20,
) -> list[dict]:
    """抓取指定平台的熱門內容。

    路由邏輯：
      mock  → 全部走 mock
      tikwm → douyin 走 TikWM（免費）；其他平台若有 Apify Actor 則走 Apify，否則 mock
      apify → 全部走 Apify；無 token 時 douyin fallback TikWM，其他 mock
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(
            f"unsupported platform={platform!r}, "
            f"valid={list(SUPPORTED_PLATFORMS)}"
        )
    if not 0 < hours <= MAX_HOURS:
        raise ValueError(f"hours must be in (0, {MAX_HOURS}], got {hours}")
    if not 0 < limit <= MAX_LIMIT:
        raise ValueError(f"limit must be in (0, {MAX_LIMIT}], got {limit}")

    backend = _resolve_backend()
    logger.info("crawler.backend=%s platform=%s category=%s", backend, platform, category)

    if backend == "mock":
        return _mock_fetch_hot_content(platform, category, hours, limit)

    if backend == "tikwm":
        if platform == "douyin":
            # douyin：TikWM 免費，省下 Apify 額度給其他平台
            return _tikwm_fetch_hot_content(platform, category, hours, limit)
        # 非 douyin：TikWM 不支援 → 若有 Apify Actor 就走 Apify
        if settings.APIFY_TOKEN and _platform_actor_id(platform):
            logger.info("crawler.tikwm_to_apify platform=%s", platform)
            return _apify_fetch_hot_content(platform, category, hours, limit)
        logger.warning(
            "crawler.tikwm_no_apify_actor platform=%s — fallback mock", platform
        )
        return _mock_fetch_hot_content(platform, category, hours, limit)

    # apify backend
    if not settings.APIFY_TOKEN:
        logger.warning("crawler.apify_no_token — douyin fallback tikwm, others mock")
        if platform == "douyin":
            return _tikwm_fetch_hot_content(platform, category, hours, limit)
        return _mock_fetch_hot_content(platform, category, hours, limit)
    return _apify_fetch_hot_content(platform, category, hours, limit)


# =========================================================
# TikWM 實作（免費，douyin 專用）
# =========================================================

def _tikwm_fetch_hot_content(
    platform: str, category: str, hours: int, limit: int
) -> list[dict]:
    """呼叫 tikwm.com 公開 API 抓 TikTok/抖音 熱門內容。

    tikwm 只支援 TikTok/douyin；其他平台 fallback mock（跟之前行為一致）。
    """
    if platform != "douyin":
        logger.warning(
            "crawler.tikwm_no_actor platform=%s — fallback to mock (tikwm douyin only)",
            platform,
        )
        return _mock_fetch_hot_content(platform, category, hours, limit)

    keywords = _CATEGORY_KEYWORDS.get(category, [category])
    keyword = keywords[0]  # tikwm feed/search 一次一個關鍵字

    try:
        items = _call_tikwm_api(keyword, limit=max(limit * 2, 12))
    except Exception as e:
        logger.error(
            "crawler.tikwm_call_failed platform=%s keyword=%s err=%s — returning empty",
            platform,
            keyword,
            type(e).__name__,
        )
        return []

    raw_mapped = [_map_tikwm_item(raw) for raw in items]
    chinese_only = [
        m for m in raw_mapped if m is not None and _is_chinese_content(m["title"])
    ]
    final = chinese_only[:limit]
    logger.info(
        "crawler.tikwm_ok platform=%s keyword=%s raw=%d chinese=%d kept=%d",
        platform, keyword, len(items), len(chinese_only), len(final),
    )
    if not final:
        logger.warning("crawler.tikwm_no_chinese platform=%s — returning empty", platform)
        return []
    return final


def _call_tikwm_api(keyword: str, *, limit: int) -> list[dict]:
    """呼叫 tikwm.com /api/feed/search。

    無需 API key，公開端點。
    回傳 data.videos list，失敗 raise Exception。
    """
    url = f"{TIKWM_BASE_URL}/feed/search"
    params = {"keywords": keyword, "count": limit}
    with httpx.Client(timeout=TIKWM_TIMEOUT_SECONDS) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        body = resp.json()

    # TikWM 成功時 code=0
    if body.get("code") != 0:
        raise RuntimeError(f"tikwm error code={body.get('code')} msg={body.get('msg')}")

    data = body.get("data") or {}
    return data.get("videos") or []


def _map_tikwm_item(raw: dict) -> dict | None:
    """把 tikwm API item 對齊 candidates.items[*] schema。"""
    if not isinstance(raw, dict):
        return None

    title = (raw.get("title") or raw.get("desc") or "").strip()[:120]
    if not title:
        return None

    video_id = raw.get("id") or raw.get("video_id") or ""
    author = raw.get("author") or {}
    username = author.get("unique_id") or author.get("uniqueId") or ""
    url = (
        f"https://www.tiktok.com/@{username}/video/{video_id}"
        if username and video_id
        else raw.get("play_url") or ""
    )

    play      = _to_int(raw.get("play") or raw.get("play_count"))
    likes     = _to_int(raw.get("digg_count") or raw.get("likes"))
    comments  = _to_int(raw.get("comment_count") or raw.get("comments"))
    shares    = _to_int(raw.get("share_count") or raw.get("shares"))
    engagement = play or (likes + comments * 5 + shares * 3) or likes or 0

    return {
        "platform": "douyin",
        "url": url,
        "source_url": url,
        "title": title,
        "engagement": int(engagement),
        "completion_rate": None,
        "topic_match": 0.0,
        "purchase_intent_density": 0.0,
        "funnel_role": None,
        "b_track_similarity": None,
    }


# =========================================================
# Apify 實作
# =========================================================

def _apify_fetch_hot_content(
    platform: str, category: str, hours: int, limit: int
) -> list[dict]:
    """呼叫 Apify Actor 抓真實熱門內容。

    失敗策略：
      - 該平台 actor 沒設定 → fallback mock
      - Apify 呼叫失敗（403、5xx、network） → 回空 list
      - 過濾完無中文結果 → 回空 list
    """
    actor_id = _platform_actor_id(platform)
    if not actor_id:
        logger.warning(
            "crawler.apify_no_actor platform=%s — fallback to mock",
            platform,
        )
        return _mock_fetch_hot_content(platform, category, hours, limit)

    keywords = _CATEGORY_KEYWORDS.get(category, [category])
    actor_input = _build_actor_input(platform, keywords=keywords, limit=limit)

    try:
        items = _call_apify_actor(actor_id, actor_input)
    except Exception as e:
        http_status = getattr(getattr(e, "response", None), "status_code", None)
        logger.error(
            "crawler.apify_call_failed platform=%s actor=%s err=%s http_status=%s — returning empty",
            platform, actor_id, type(e).__name__, http_status,
        )
        if platform == "douyin":
            logger.info("crawler.apify_douyin_fallback_tikwm")
            return _tikwm_fetch_hot_content(platform, category, hours, limit)
        return []

    raw_mapped = [_map_actor_item(platform, raw) for raw in items]
    chinese_only = [
        m for m in raw_mapped if m is not None and _is_chinese_content(m["title"])
    ]
    final = chinese_only[:limit]
    logger.info(
        "crawler.apify_ok platform=%s actor=%s raw=%d chinese=%d kept=%d",
        platform, actor_id, len(items), len(chinese_only), len(final),
    )
    if not final:
        logger.warning("crawler.apify_no_chinese platform=%s — returning empty", platform)
        return []
    return final


def _platform_actor_id(platform: str) -> str:
    return {
        "douyin": APIFY_ACTOR_DOUYIN,
        "xiaohongshu": APIFY_ACTOR_XIAOHONGSHU,
    }.get(platform, "")


def _call_apify_actor(actor_id: str, actor_input: dict) -> list[dict]:
    """同步呼叫 Apify Actor，Token 走 Authorization header。"""
    url = (
        f"{APIFY_BASE_URL}/acts/{actor_id.replace('/', '~')}"
        f"/run-sync-get-dataset-items"
    )
    headers = {"Authorization": f"Bearer {settings.APIFY_TOKEN}"}
    with httpx.Client(timeout=APIFY_TIMEOUT_SECONDS) as client:
        resp = client.post(url, headers=headers, json=actor_input)
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else []


def _build_actor_input(
    platform: str, *, keywords: list[str], limit: int
) -> dict[str, Any]:
    over_fetch = max(limit * 2, 12)
    if platform == "douyin":
        return {
            "hashtags": keywords,
            "resultsPerPage": over_fetch,
            "proxyCountryCode": "TW",
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
            "shouldDownloadSubtitles": False,
        }
    if platform == "xiaohongshu":
        xhs_limit = min(over_fetch, 12)
        actor_id = APIFY_ACTOR_XIAOHONGSHU
        proxy_cn: dict[str, Any] = {
            "useApifyProxy": True,
            "apifyProxyCountry": "CN",
        }
        if "zhorex/rednote-xiaohongshu-scraper" in actor_id:
            return {
                "mode": "search",
                "keywords": [keywords[0]],
                "maxItems": xhs_limit,
                "proxyConfiguration": proxy_cn,
            }
        if "zen-studio/rednote-search-scraper" in actor_id:
            return {
                "keywords": [keywords[0]],
                "maxResults": xhs_limit,
                "sortType": "popularity_descending",
                "noteType": "all",
                "timeFilter": "all",
                "topUpFromOtherSorts": True,
            }
        if "dltik/rednote-xiaohongshu-scraper" in actor_id:
            return {
                "mode": "search",
                "queries": [keywords[0]],
                "maxResultsPerInput": xhs_limit,
            }
        return {
            "mode": "search",
            "searchQuery": keywords[0],
            "maxResults": xhs_limit,
            "sortBy": "popularity_descending",
        }
    return {"keywords": keywords, "limit": over_fetch}


def _map_actor_item(platform: str, raw: dict) -> dict | None:
    """把 Apify actor raw item 對齊 candidates.items[*] schema。"""
    if not isinstance(raw, dict):
        return None

    title = _first_text(
        raw,
        "text", "title", "displayTitle", "desc", "description", "content",
        "noteTitle",
    )
    title = (title or "").strip()[:120]
    if not title:
        return None

    url = _extract_source_url(raw, platform)
    if not url:
        logger.warning(
            "crawler.apify_missing_source_url platform=%s raw_keys=%s",
            platform,
            sorted(raw.keys()),
        )
        return None

    plays    = _to_int(raw.get("playCount") or raw.get("viewCount") or raw.get("views"))
    likes    = _to_int(_first_value(raw, "diggCount", "likes", "likeCount", "liked_count"))
    comments = _to_int(_first_value(raw, "commentCount", "comments", "comment_count"))
    shares   = _to_int(_first_value(raw, "shareCount", "shares", "share_count"))
    collects = _to_int(_first_value(raw, "collectCount", "collectedCount", "collected_count"))

    interactions = raw.get("interactions")
    if isinstance(interactions, dict):
        likes = likes or _to_int(interactions.get("liked_count") or interactions.get("likeCount"))
        comments = comments or _to_int(interactions.get("comment_count") or interactions.get("commentCount"))
        shares = shares or _to_int(interactions.get("share_count") or interactions.get("shareCount"))
        collects = collects or _to_int(interactions.get("collected_count") or interactions.get("collectCount"))

    # zen-studio/rednote-search-scraper 使用 interactInfo（而非 interactions）
    interact_info = raw.get("interactInfo") or {}
    if isinstance(interact_info, dict):
        likes = likes or _to_int(interact_info.get("likedCount") or interact_info.get("liked_count") or 0)
        comments = comments or _to_int(interact_info.get("commentCount") or interact_info.get("comment_count") or 0)
        shares = shares or _to_int(interact_info.get("shareCount") or interact_info.get("share_count") or 0)
        collects = collects or _to_int(interact_info.get("collectCount") or interact_info.get("collectedCount") or 0)

    engagement = plays or (likes + comments * 5 + shares * 3) or likes or 0
    if platform == "xiaohongshu":
        engagement = plays or (likes + collects * 2 + comments * 5 + shares * 3) or likes or 0

    completion_rate = raw.get("completionRate")
    if completion_rate is not None:
        try:
            completion_rate = float(completion_rate)
        except (TypeError, ValueError):
            completion_rate = None

    # ── XHS：額外擷取 preview 資料（圖片、作者、全文），供 Firestore 快取 ─────
    xhs_preview: dict | None = None
    if platform == "xiaohongshu":
        raw_images = (
            raw.get("imageList") or raw.get("images") or
            raw.get("image_list") or raw.get("imageUrls") or
            raw.get("cover") and [raw["cover"]] or []
        )
        # cover 欄位可能是 dict，包裝成 list 處理
        if isinstance(raw.get("cover"), dict) and not raw_images:
            raw_images = [raw["cover"]]
        preview_imgs: list[str] = []
        for img in raw_images[:4]:
            if isinstance(img, dict):
                img_url = (
                    img.get("url") or img.get("urlDefault") or
                    img.get("src") or img.get("originUrl") or
                    img.get("imageUrl") or ""
                )
            elif isinstance(img, str):
                img_url = img
            else:
                img_url = ""
            if img_url:
                preview_imgs.append(img_url)

        p_author_obj = raw.get("author") or raw.get("user") or raw.get("userInfo") or {}
        p_author = (
            _first_text(p_author_obj, "nickname", "name", "username", "nickName")
            if isinstance(p_author_obj, dict) else ""
        ) or _first_text(raw, "authorName", "nickName", "nickname")

        p_content = _first_text(raw, "description", "content", "desc", "body", "noteDesc")
        if p_content == title:
            p_content = ""  # 避免重複

        p_interact = raw.get("interactInfo") or {}
        p_likes = likes or _to_int(
            p_interact.get("likedCount") or p_interact.get("liked_count") or 0
        )
        p_comments = comments or _to_int(
            p_interact.get("commentCount") or p_interact.get("comment_count") or 0
        )
        p_collects = collects or _to_int(
            p_interact.get("collectedCount") or p_interact.get("collectCount") or 0
        )

        if preview_imgs or p_content:
            xhs_preview = {
                "title":    title,
                "images":   preview_imgs,
                "author":   p_author,
                "content":  p_content[:600] if p_content else "",
                "likes":    p_likes,
                "comments": p_comments,
                "collects": p_collects,
            }

    result: dict = {
        "platform": platform,
        "url": url,
        "source_url": url,
        "title": title,
        "engagement": int(engagement),
        "completion_rate": completion_rate,
        "topic_match": 0.0,
        "purchase_intent_density": 0.0,
        "funnel_role": None,
        "b_track_similarity": None,
    }
    if xhs_preview is not None:
        result["preview"] = xhs_preview
    return result


def _to_int(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _first_value(raw: dict, *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_text(raw: dict, *keys: str) -> str:
    value = _first_value(raw, *keys)
    if isinstance(value, dict):
        return ""
    return str(value or "")


def _extract_source_url(raw: dict, platform: str) -> str:
    """Return the public original post URL for a crawled item."""

    # 小紅書：若 actor 回傳帶 xsec_token 的 explore URL，優先保留，供預覽抓單篇詳情。
    # 否則用 note_id 建構乾淨 explore URL，避開 xhslink.com 短網址。
    if platform == "xiaohongshu":
        token_url = _first_text(
            raw,
            "postUrl", "post_url", "noteUrl", "note_url", "url",
            "canonicalUrl", "shareUrl", "share_url", "link", "href",
        ).strip()
        if token_url and "xiaohongshu.com/explore/" in token_url and "xsec_token=" in token_url:
            return token_url

        note_id = _first_text(raw, "note_id", "noteId", "noteid").strip()
        # 嚴格驗證 hex note_id，避免誤用其他欄位的值
        if note_id and re.match(r"^[0-9a-f]{16,32}$", note_id):
            return f"https://www.xiaohongshu.com/explore/{note_id}"
        # fallback：若 note_id 找不到，嘗試從 raw["id"] 取（部分 actor 版本用法）
        alt_id = _first_text(raw, "id").strip()
        if alt_id and re.match(r"^[0-9a-f]{16,32}$", alt_id):
            return f"https://www.xiaohongshu.com/explore/{alt_id}"

    # 通用 URL 欄位（douyin / threads / 小紅書 fallback）
    url = _first_text(
        raw,
        "webVideoUrl", "url", "postUrl", "post_url", "noteUrl", "note_url",
        "link", "shareUrl", "share_url", "href", "canonicalUrl",
    ).strip()
    if url:
        return url

    if platform == "douyin":
        video_id = _first_text(raw, "id", "video_id", "awemeId").strip()
        author = raw.get("author") or raw.get("authorMeta") or {}
        username = ""
        if isinstance(author, dict):
            username = _first_text(author, "unique_id", "uniqueId", "name", "nickname")
        if username and video_id:
            return f"https://www.tiktok.com/@{username}/video/{video_id}"

    return ""


# =========================================================
# 小紅書貼文預覽（post_details 模式，後端代理）
# =========================================================

def fetch_xhs_post_details(note_url: str) -> dict | None:
    """用 zhorex actor post_details 模式抓單篇小紅書貼文。

    費用：$0.010/次（供台灣使用者不需 VPN 預覽原文）。
    失敗時回傳 None，由呼叫方決定如何處理。
    """
    actor_id = APIFY_ACTOR_XIAOHONGSHU_PREVIEW or APIFY_ACTOR_XIAOHONGSHU
    if not actor_id or not settings.APIFY_TOKEN:
        logger.warning(
            "crawler.xhs_preview_no_config actor=%s has_token=%s",
            bool(actor_id), bool(settings.APIFY_TOKEN),
        )
        return None

    actor_input = _build_xhs_preview_input(actor_id, note_url)
    logger.info(
        "crawler.xhs_preview_call actor=%s url=%s input_keys=%s",
        actor_id, note_url, list(actor_input.keys()),
    )
    try:
        items = _call_apify_actor(actor_id, actor_input)
    except Exception as e:
        status_info = ""
        if hasattr(e, "response") and e.response is not None:
            status_info = f" http_status={e.response.status_code}"
        logger.error(
            "crawler.xhs_post_details_failed url=%s actor=%s err=%s%s",
            note_url, actor_id, type(e).__name__, status_info,
        )
        return None

    logger.info(
        "crawler.xhs_preview_result actor=%s url=%s items_count=%d",
        actor_id, note_url, len(items),
    )
    if not items:
        logger.warning(
            "crawler.xhs_preview_empty actor=%s url=%s — actor returned no items",
            actor_id, note_url,
        )
        return None

    # 過濾 Apify 內部 metadata 項目（只有 _ 前綴 key，無真實資料）
    real_items = [i for i in items if any(not k.startswith("_") for k in i.keys())]
    if not real_items:
        logger.warning(
            "crawler.xhs_preview_metadata_only actor=%s url=%s keys=%s — no real post data",
            actor_id, note_url, sorted(items[0].keys()),
        )
        return None

    return _map_xhs_post_detail(_unwrap_xhs_post_detail(real_items[0]))


def _unwrap_xhs_post_detail(raw: dict) -> dict:
    """Return the most likely nested note payload from actor-specific wrappers."""
    for key in ("data", "note", "post", "detail", "result"):
        value = raw.get(key)
        if isinstance(value, dict):
            nested = _unwrap_xhs_post_detail(value)
            if _xhs_detail_score(nested) > _xhs_detail_score(raw):
                return nested
    return raw


def _xhs_detail_score(raw: dict) -> int:
    score = 0
    if _first_text(raw, "title", "displayTitle", "noteTitle", "desc", "text"):
        score += 1
    if _first_text(raw, "description", "content", "body"):
        score += 2
    if raw.get("imageList") or raw.get("images") or raw.get("image_list") or raw.get("pics"):
        score += 2
    if raw.get("user") or raw.get("author") or raw.get("userInfo"):
        score += 1
    return score


def _build_xhs_preview_input(actor_id: str, note_url: str) -> dict[str, Any]:
    """Return the actor-specific input shape for a single XHS note preview.

    所有 actor 都帶 proxyConfiguration（中國大陸 IP），繞過台灣地理封鎖。
    """
    # 中國代理設定（小紅書在台灣 TCP-level 封鎖，必須走 CN IP）
    proxy_cn: dict[str, Any] = {
        "useApifyProxy": True,
        "apifyProxyCountry": "CN",
    }

    if "curious_coder/xiaohongshu-scraper" in actor_id:
        return {
            "startUrls": [{"url": note_url}],
            "maxItems": 1,
            "proxyConfiguration": proxy_cn,
        }
    if "dltik/rednote-xiaohongshu-scraper" in actor_id:
        actor_input: dict[str, Any] = {
            "mode": "post",
            "noteUrls": [note_url],
            "proxyConfiguration": proxy_cn,
        }
        if XHS_COOKIES:
            actor_input["cookiesString"] = XHS_COOKIES
        return actor_input
    if "zhorex/rednote-xiaohongshu-scraper" in actor_id:
        return {
            "mode": "post_details",
            "postUrls": [note_url],
            "proxyConfiguration": proxy_cn,
        }
    # 預設用 startUrls（通用 Apify 格式）
    return {
        "startUrls": [{"url": note_url}],
        "maxItems": 1,
        "proxyConfiguration": proxy_cn,
    }


def _map_xhs_post_detail(raw: dict) -> dict:
    """Map actor post_details output → preview schema.

    支援多種 actor 輸出格式：
    - curious_coder: title, description, imageList[{url}], author.nickname,
                     interactInfo.{likedCount, commentCount, collectedCount}
    - dltik/zhorex: title, content, images[{url}], author/user.nickname,
                    diggCount/likeCount, commentCount, collectCount
    """
    logger.info("crawler.xhs_detail_raw_keys top_keys=%s", sorted(raw.keys()))

    # ── 標題 ──────────────────────────────────────────────────────────────────
    title = _first_text(raw, "title", "displayTitle", "noteTitle", "desc", "text")

    # ── 內文 ──────────────────────────────────────────────────────────────────
    content = _first_text(raw, "description", "content", "desc", "body", "text")
    # 避免 title == content（部分 actor 把全文放在 title）
    if content and content == title:
        content = ""

    # ── 圖片（最多 4 張）──────────────────────────────────────────────────────
    # curious_coder → imageList；其他 actor → images
    raw_images = (
        raw.get("imageList") or
        raw.get("images") or
        raw.get("image_list") or
        raw.get("pics") or
        []
    )
    images: list[str] = []
    for img in raw_images[:4]:
        img_url = ""
        if isinstance(img, dict):
            img_url = (
                img.get("url") or img.get("urlDefault") or
                img.get("src") or img.get("imageUrl") or
                img.get("originUrl") or ""
            )
        elif isinstance(img, str):
            img_url = img
        if img_url:
            images.append(img_url)

    # ── 作者 ──────────────────────────────────────────────────────────────────
    author_obj = raw.get("author") or raw.get("user") or {}
    author_name = (
        _first_text(author_obj, "nickname", "name", "username")
        if isinstance(author_obj, dict) else ""
    )
    author_name = author_name or _first_text(raw, "authorName", "nickname", "userName")

    # ── 互動數 ────────────────────────────────────────────────────────────────
    # curious_coder → interactInfo.{likedCount, commentCount, collectedCount}
    # 其他 → 直接在頂層 or interactions.*
    interact = raw.get("interactInfo") or raw.get("interactions") or {}

    likes = _to_int(_first_value(raw, "diggCount", "likes", "likeCount", "liked_count"))
    if not likes and isinstance(interact, dict):
        likes = _to_int(
            interact.get("likedCount") or interact.get("liked_count") or
            interact.get("likeCount") or interact.get("diggCount") or 0
        )

    comments = _to_int(_first_value(raw, "commentCount", "comments", "comment_count"))
    if not comments and isinstance(interact, dict):
        comments = _to_int(interact.get("commentCount") or interact.get("comment_count") or 0)

    collects = _to_int(_first_value(raw, "collectCount", "collectedCount", "collected_count", "saves"))
    if not collects and isinstance(interact, dict):
        collects = _to_int(
            interact.get("collectedCount") or interact.get("collectCount") or
            interact.get("collected_count") or 0
        )

    return {
        "title":    (title   or "")[:200],
        "content":  (content or "")[:600],
        "images":   images,
        "author":   author_name,
        "likes":    likes,
        "comments": comments,
        "collects": collects,
    }


# =========================================================
# Mock 實作（本機開發 / 備用）
# =========================================================

def _candidate_item(
    *,
    platform: str,
    index: int,
    title: str,
    engagement: int,
    completion_rate: float | None = None,
) -> dict[str, Any]:
    return {
        "platform": platform,
        "url": f"https://example.com/{platform}/mock-{index:03d}",
        "source_url": f"https://example.com/{platform}/mock-{index:03d}",
        "title": title,
        "engagement": engagement,
        "completion_rate": completion_rate,
        "topic_match": 0.0,
        "purchase_intent_density": 0.0,
        "funnel_role": None,
        "b_track_similarity": None,
    }


_MOCK_FIXTURES: dict[tuple[str, str], list[tuple[str, int, float | None]]] = {
    ("xiaohongshu", "髮品"): [
        ("頭髮乾燥毛躁？這款髮膜我用了 3 週真的有感", 282_000, None),
        ("受損髮質救星！分享我的髮膜養護 SOP", 156_000, None),
        ("頭皮出油怎麼辦？這支洗髮精解決我多年困擾", 198_000, None),
        ("自從用了這個護髮油，毛躁分岔再見", 121_000, None),
    ],
    ("xiaohongshu", "美妝"): [
        ("敏感肌的救星精華｜我的暗沉變化", 245_000, None),
        ("保養 SOP 大公開，毛孔變細的祕密", 187_000, None),
    ],
    ("xiaohongshu", "美食"): [
        ("減脂便當這樣做｜不挨餓還能瘦", 312_000, None),
        ("氣泡水自製食譜，比手搖店好喝", 142_000, None),
    ],
    ("douyin", "髮品"): [
        ("髮膜對比實測 5 款｜真實到爆的差距", 412_000, 0.78),
        ("頭皮按摩+護髮 之後頭髮真的不一樣", 287_000, 0.65),
    ],
    ("douyin", "美妝"): [
        ("底妝大對比｜油肌的選擇答案", 356_000, 0.72),
    ],
    ("douyin", "美食"): [
        ("增肌餐這樣搭｜健身教練的菜單", 289_000, 0.69),
    ],
}


def _mock_fetch_hot_content(
    platform: str, category: str, hours: int, limit: int
) -> list[dict]:
    """確定性 mock 資料；同樣的 (platform, category) 永遠回同樣資料。"""
    fixtures = _MOCK_FIXTURES.get((platform, category))
    if not fixtures:
        fixtures = [
            (f"[MOCK] {platform} 熱門內容 {i}", 100_000 + i * 10_000, None)
            for i in range(2)
        ]
    return [
        _candidate_item(
            platform=platform,
            index=i,
            title=title,
            engagement=engagement,
            completion_rate=completion_rate,
        )
        for i, (title, engagement, completion_rate) in enumerate(fixtures[:limit])
    ]

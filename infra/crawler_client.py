"""三平台爬取輔助 client 封裝 — Phase 3 + Apify + TikWM 整合。

責任：
  - fetch_hot_content(platform, category, hours, limit) → list[dict]
  - 三平台：xiaohongshu / douyin / threads
  - 介面對齊 candidates collection 的 items[*] 欄位（spec-developer）
  - 後端模式（CRAWLER_BACKEND env）：
      mock   → 回確定性測試資料
      tikwm  → 呼叫 tikwm.com 公開 API（免費，抖音/TikTok）
      apify  → 呼叫 Apify Actor API（需設 SF_APIFY_TOKEN）
      未設定  → 有 APIFY_TOKEN 走 apify，否則走 tikwm

設計：
  - tikwm 只支援 douyin；xiaohongshu / threads 無 tikwm actor，各自 fallback mock
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

SUPPORTED_PLATFORMS = ("xiaohongshu", "douyin", "threads")
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
APIFY_ACTOR_XIAOHONGSHU = os.getenv("APIFY_ACTOR_XIAOHONGSHU", "")
APIFY_ACTOR_THREADS = os.getenv("APIFY_ACTOR_THREADS", "")

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
    """抓取指定平台的熱門內容。"""
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
        return _tikwm_fetch_hot_content(platform, category, hours, limit)
    # apify
    if not settings.APIFY_TOKEN:
        logger.warning(
            "crawler.apify_no_token — fallback to tikwm"
        )
        return _tikwm_fetch_hot_content(platform, category, hours, limit)
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
        logger.error(
            "crawler.apify_call_failed platform=%s actor=%s err=%s — returning empty",
            platform, actor_id, type(e).__name__,
        )
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
        "threads": APIFY_ACTOR_THREADS,
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
        return {"keyword": keywords[0], "keywords": keywords, "maxItems": over_fetch}
    if platform == "threads":
        return {"search_keyword": keywords[0], "max_posts": over_fetch}
    return {"keywords": keywords, "limit": over_fetch}


def _map_actor_item(platform: str, raw: dict) -> dict | None:
    """把 Apify actor raw item 對齊 candidates.items[*] schema。"""
    if not isinstance(raw, dict):
        return None

    title = (
        raw.get("text") or raw.get("title") or raw.get("desc")
        or raw.get("description") or ""
    )
    title = (title or "").strip()[:120]
    if not title:
        return None

    url = (
        raw.get("webVideoUrl") or raw.get("url") or raw.get("postUrl")
        or raw.get("link") or ""
    )

    plays    = _to_int(raw.get("playCount") or raw.get("viewCount") or raw.get("views"))
    likes    = _to_int(raw.get("diggCount") or raw.get("likes") or raw.get("likeCount"))
    comments = _to_int(raw.get("commentCount") or raw.get("comments"))
    shares   = _to_int(raw.get("shareCount") or raw.get("shares"))
    engagement = plays or (likes + comments * 5 + shares * 3) or likes or 0

    completion_rate = raw.get("completionRate")
    if completion_rate is not None:
        try:
            completion_rate = float(completion_rate)
        except (TypeError, ValueError):
            completion_rate = None

    return {
        "platform": platform,
        "url": url,
        "title": title,
        "engagement": int(engagement),
        "completion_rate": completion_rate,
        "topic_match": 0.0,
        "purchase_intent_density": 0.0,
        "funnel_role": None,
        "b_track_similarity": None,
    }


def _to_int(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


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
    ("threads", "髮品"): [
        ("分享我的養髮日常｜每週兩次的儀式感", 89_000, None),
        ("受損髮質這樣救！我的養髮日記第 28 天", 124_000, None),
    ],
    ("threads", "美妝"): [
        ("我的早晚保養流程｜30 歲後的選擇", 67_000, None),
    ],
    ("threads", "美食"): [
        ("早餐這樣準備一週｜上班族友善食譜", 92_000, None),
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

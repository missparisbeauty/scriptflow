"""三平台爬取輔助 client 封裝 — Phase 3 + Apify 整合。

責任：
  - fetch_hot_content(platform, category, hours, limit) → list[dict]
  - 三平台：xiaohongshu / douyin / threads
  - 介面對齊 candidates collection 的 items[*] 欄位（spec-developer）
  - 後端模式（CRAWLER_BACKEND env）：
      mock   → 回確定性測試資料（無 token 時自動降級）
      apify  → 呼叫 Apify Actor API（需設 SF_APIFY_TOKEN）

設計：
  - Apify Actor IDs 透過 env 可覆寫，預設用 clockworks/free-tiktok-scraper
  - 沒設定 actor ID 的平台單獨 fallback 到 mock（不整批掉）
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
DEFAULT_TIMEOUT_SECONDS = 90  # Apify run-sync 較慢
MAX_HOURS = 168
MAX_LIMIT = 50

APIFY_BASE_URL = "https://api.apify.com/v2"

# 各平台對應的 Apify Actor ID（env 可覆寫）
# clockworks/free-tiktok-scraper 是免費熱門 actor，抖音/TikTok 通用
APIFY_ACTOR_DOUYIN = os.getenv(
    "APIFY_ACTOR_DOUYIN", "clockworks/free-tiktok-scraper"
)
# 小紅書與 Threads 預設不啟用（user 需自行從 Apify Store 選 actor 並設 env）
APIFY_ACTOR_XIAOHONGSHU = os.getenv("APIFY_ACTOR_XIAOHONGSHU", "")
APIFY_ACTOR_THREADS = os.getenv("APIFY_ACTOR_THREADS", "")


# 各分類對應的搜尋關鍵字（給 Apify 搜尋用）
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "髮品": ["髮膜", "護髮", "染髮"],
    "美妝": ["彩妝", "保養", "化妝品"],
    "美食": ["美食", "食譜", "便當"],
}

# --- 語言過濾（只留中文圈內容） ---
# CJK 漢字（中日韓共用，但日韓會搭配各自的特殊字元）
_CJK_RE = re.compile(r"[一-鿿]")
# 日文平假名 + 片假名（出現即判定為日文，排除）
_JAPANESE_KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")
# 韓文諺文（出現即判定為韓文，排除）
_KOREAN_RE = re.compile(r"[가-힯]")
# 純英文判斷：去掉空白/標點/數字後，剩下的全是 ASCII
_NON_LETTER_RE = re.compile(r"[\s\W\d#@_]+")


def _is_chinese_content(text: str) -> bool:
    """判斷文字是否為中文（繁體/簡體）。

    規則：
      ✓ 必須包含 CJK 漢字
      ✗ 不能含日文假名（あ-ん、ア-ン）
      ✗ 不能含韓文諺文（가-힣）
    """
    if not text:
        return False
    if _JAPANESE_KANA_RE.search(text):
        return False
    if _KOREAN_RE.search(text):
        return False
    return bool(_CJK_RE.search(text))


# --- 對外 API ---


def is_mock() -> bool:
    """是否走 mock 模式。

    優先順序：
      1. CRAWLER_BACKEND=mock 顯式 mock
      2. 沒 APIFY_TOKEN → 自動 mock
    """
    if os.getenv("CRAWLER_BACKEND", "").lower() == "mock":
        return True
    return not settings.APIFY_TOKEN


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

    if is_mock():
        return _mock_fetch_hot_content(platform, category, hours, limit)
    return _real_fetch_hot_content(platform, category, hours, limit)


# --- Apify 真實實作 ---


def _platform_actor_id(platform: str) -> str:
    return {
        "douyin": APIFY_ACTOR_DOUYIN,
        "xiaohongshu": APIFY_ACTOR_XIAOHONGSHU,
        "threads": APIFY_ACTOR_THREADS,
    }.get(platform, "")


def _real_fetch_hot_content(
    platform: str, category: str, hours: int, limit: int
) -> list[dict]:
    """呼叫 Apify Actor 抓真實熱門內容。

    沒設定該平台 actor 時，單獨 fallback 到 mock（不影響其他平台）。
    """
    actor_id = _platform_actor_id(platform)
    if not actor_id:
        logger.warning(
            "crawler.no_actor platform=%s — fallback to mock for this platform",
            platform,
        )
        return _mock_fetch_hot_content(platform, category, hours, limit)

    keywords = _CATEGORY_KEYWORDS.get(category, [category])
    actor_input = _build_actor_input(platform, keywords=keywords, limit=limit)

    try:
        items = _call_apify_actor(actor_id, actor_input)
    except Exception as e:
        logger.error(
            "crawler.apify_call_failed platform=%s actor=%s err=%s",
            platform,
            actor_id,
            type(e).__name__,
        )
        # 整體 actor 呼叫失敗也 fallback 到 mock，不擋住爬蟲流程
        return _mock_fetch_hot_content(platform, category, hours, limit)

    # 1. 映射欄位 → 2. 語言過濾（只留中文圈）→ 3. 取前 limit 筆
    raw_mapped = [_map_actor_item(platform, raw) for raw in items]
    chinese_only = [
        m for m in raw_mapped if m is not None and _is_chinese_content(m["title"])
    ]
    final = chinese_only[:limit]
    logger.info(
        "crawler.apify_ok platform=%s actor=%s raw=%d chinese=%d kept=%d",
        platform,
        actor_id,
        len(items),
        len(chinese_only),
        len(final),
    )
    # 過濾後若為空（例如該關鍵字幾乎沒中文內容）→ fallback 到 mock 確保前端有東西看
    if not final:
        logger.warning(
            "crawler.no_chinese_results platform=%s — fallback to mock",
            platform,
        )
        return _mock_fetch_hot_content(platform, category, hours, limit)
    return final


def _call_apify_actor(actor_id: str, actor_input: dict) -> list[dict]:
    """同步呼叫 Apify Actor，等執行完拿 dataset items。

    Token 走 Authorization header（rule-cloud：避免 secret 進 URL/log）。
    """
    url = (
        f"{APIFY_BASE_URL}/acts/{actor_id.replace('/', '~')}"
        f"/run-sync-get-dataset-items"
    )
    headers = {"Authorization": f"Bearer {settings.APIFY_TOKEN}"}
    with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        resp = client.post(url, headers=headers, json=actor_input)
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else []


def _build_actor_input(
    platform: str, *, keywords: list[str], limit: int
) -> dict[str, Any]:
    """組 actor input。各 actor schema 不一樣，這裡集中映射。

    多取 3 倍量，因為後處理會過濾掉非中文內容。
    """
    over_fetch = max(limit * 3, 30)
    if platform == "douyin":
        # clockworks/free-tiktok-scraper：proxyCountryCode 走台灣 IP，
        # 增加抓到中文圈內容的機率
        return {
            "hashtags": keywords,
            "resultsPerPage": over_fetch,
            "proxyCountryCode": "TW",
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
            "shouldDownloadSubtitles": False,
        }
    if platform == "xiaohongshu":
        return {
            "keyword": keywords[0],
            "keywords": keywords,
            "maxItems": over_fetch,
        }
    if platform == "threads":
        return {
            "search_keyword": keywords[0],
            "max_posts": over_fetch,
        }
    return {"keywords": keywords, "limit": over_fetch}


def _map_actor_item(platform: str, raw: dict) -> dict | None:
    """把 Apify actor 回傳的 raw item 對齊 candidates.items[*] schema。

    各 actor 欄位不一致，這裡盡力歸一化；找不到必要欄位回 None。
    """
    if not isinstance(raw, dict):
        return None

    # 標題
    title = (
        raw.get("text")
        or raw.get("title")
        or raw.get("desc")
        or raw.get("description")
        or ""
    )
    title = (title or "").strip()
    if not title:
        return None
    title = title[:120]  # 控制長度

    # URL
    url = (
        raw.get("webVideoUrl")
        or raw.get("url")
        or raw.get("postUrl")
        or raw.get("link")
        or ""
    )

    # 互動數（依 actor 不同，名稱混搭）
    plays = _to_int(raw.get("playCount") or raw.get("viewCount") or raw.get("views"))
    likes = _to_int(raw.get("diggCount") or raw.get("likes") or raw.get("likeCount"))
    comments = _to_int(raw.get("commentCount") or raw.get("comments"))
    shares = _to_int(raw.get("shareCount") or raw.get("shares"))
    engagement = plays or (likes + comments * 5 + shares * 3) or likes or 0

    # 完看率（TikTok 沒有，部分 actor 有）
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
        # 由 CrawlerService 用 domain.rules 計算後填入
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


# --- Mock 實作（保留作 fallback） ---


def _candidate_item(
    *,
    platform: str,
    index: int,
    title: str,
    engagement: int,
    completion_rate: float | None = None,
) -> dict[str, Any]:
    """產生符合 candidates.items[*] schema 的單筆。"""
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

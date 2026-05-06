"""三平台爬取輔助 client 封裝 — Phase 3。

責任：
  - fetch_hot_content(platform, category, hours, limit) → list[dict]
  - 三平台：xiaohongshu / douyin / threads
  - 介面對齊 candidates collection 的 items[*] 欄位（spec-developer）
  - 沒設 CRAWLER_CREDENTIAL 或 CRAWLER_BACKEND=mock 時走 mock

設計：
  - 真實爬取輔助是外部第三方服務（介面待 user 提供 credential 後實作）
  - mock 回確定性資料，方便 service 層測試流程
  - SUPPORTED_PLATFORMS 跟 domain.compliance_rules.PLATFORMS 一致
"""

from __future__ import annotations

import logging
import os
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

# --- 設定 ---

SUPPORTED_PLATFORMS = ("xiaohongshu", "douyin", "threads")
DEFAULT_TIMEOUT_SECONDS = 30
MAX_HOURS = 168  # 最多回看一週
MAX_LIMIT = 50


# --- 對外 API ---


def is_mock() -> bool:
    if os.getenv("CRAWLER_BACKEND", "").lower() == "mock":
        return True
    return not settings.CRAWLER_CREDENTIAL


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

    Args:
        platform: SUPPORTED_PLATFORMS 之一
        category: 「美妝」/「美食」/「髮品」
        hours: 回看時數，1 ~ MAX_HOURS
        limit: 回傳筆數上限，1 ~ MAX_LIMIT

    Returns:
        list of dict，欄位對齊 candidates.items[*]：
          {platform, url, title, engagement, completion_rate,
           topic_match, purchase_intent_density, funnel_role, b_track_similarity}
        topic_match / purchase_intent_density / funnel_role 在這層先給 0/None，
        由 CrawlerService 用 domain.rules 計算後寫回。
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

    if is_mock():
        return _mock_fetch_hot_content(platform, category, hours, limit)
    return _real_fetch_hot_content(platform, category, hours, limit)


# --- 真實實作（待第三方爬取服務介面確定） ---


def _real_fetch_hot_content(
    platform: str, category: str, hours: int, limit: int
) -> list[dict]:
    """呼叫真實爬取輔助服務。

    介面待 user 提供 CRAWLER_CREDENTIAL 與服務文件後實作。
    暫時拋 NotImplementedError，避免靜默回 mock 資料。
    """
    raise NotImplementedError(
        "real crawler client not implemented yet. "
        "Set CRAWLER_BACKEND=mock or configure CRAWLER_CREDENTIAL with "
        "third-party crawler service spec."
    )


# --- Mock 實作 ---


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
        # 由 CrawlerService 用 domain.rules 計算後填入
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
        # 找不到對應 fixture 時，回 2 筆通用資料讓 service 流程跑得通
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

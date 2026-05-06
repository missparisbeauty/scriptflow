"""合規禁詞清單（按平台分）— Phase 1。

三平台禁詞分布：
  - xiaohongshu（小紅書）：醫療療效類最嚴
  - douyin（抖音）：極限詞、保證類嚴
  - threads（Meta）：絕對化、誇大類

設計：
  - 初版聚焦 20+ 高風險詞（dev-order.md「先做與後補界線」）
  - 每個禁詞附帶建議替換詞，前端可直接顯示給小編
  - scan() 回傳「違規詞 + 建議」清單，無違規回傳空 list
"""

from __future__ import annotations

from dataclasses import dataclass

# --- 平台清單 ---

PLATFORMS = ("xiaohongshu", "douyin", "threads")


# --- 禁詞資料結構 ---


@dataclass(frozen=True)
class BannedWord:
    """單一禁詞。

    Attributes:
        word: 違規詞（精準字串比對）
        suggest: 建議替換詞（給小編參考）
        reason: 違規類別（極限詞 / 療效 / 保證 / 誇大）
    """

    word: str
    suggest: str
    reason: str


# --- 共用禁詞（三平台都禁） ---

_COMMON: tuple[BannedWord, ...] = (
    BannedWord("最", "頂級／首選", "極限詞"),
    BannedWord("第一", "領先", "極限詞"),
    BannedWord("唯一", "獨家／少見", "極限詞"),
    BannedWord("絕對", "明顯／高度", "極限詞"),
    BannedWord("百分百", "顯著", "極限詞"),
    BannedWord("100%", "顯著", "極限詞"),
    BannedWord("永久", "長效", "誇大"),
    BannedWord("一勞永逸", "持久", "誇大"),
    BannedWord("保證", "幫助", "保證類"),
    BannedWord("立刻見效", "感受變化", "誇大"),
)


# --- 平台特化禁詞 ---

_PLATFORM_SPECIFIC: dict[str, tuple[BannedWord, ...]] = {
    "xiaohongshu": (
        BannedWord("治癒", "舒緩", "療效"),
        BannedWord("治療", "改善", "療效"),
        BannedWord("醫療級", "專業級", "療效"),
        BannedWord("藥用", "護理用", "療效"),
        BannedWord("根治", "改善", "療效"),
        BannedWord("無副作用", "溫和", "療效"),
    ),
    "douyin": (
        BannedWord("頂級", "高品質", "極限詞"),
        BannedWord("第一名", "推薦", "極限詞"),
        BannedWord("國家級", "通過驗證", "誇大"),
        BannedWord("世界級", "國際品質", "誇大"),
        BannedWord("史上最", "突破性", "極限詞"),
    ),
    "threads": (
        BannedWord("神奇", "顯著", "誇大"),
        BannedWord("奇蹟", "驚喜", "誇大"),
        BannedWord("逆天", "突破", "誇大"),
    ),
}


def _rules_for(platform: str) -> tuple[BannedWord, ...]:
    """取得指定平台的完整禁詞清單（共用 + 平台特化）。"""
    if platform not in PLATFORMS:
        return ()
    return _COMMON + _PLATFORM_SPECIFIC.get(platform, ())


# --- 對外 API ---


def list_platforms() -> list[str]:
    """回傳所有支援的平台名稱。"""
    return list(PLATFORMS)


def scan(text: str, platform: str) -> list[dict]:
    """掃描文字違規詞。

    Args:
        text: 要檢查的文字（單一版本腳本）
        platform: 平台名稱（PLATFORMS 之一）

    Returns:
        違規清單：[{"word": "最", "suggest": "頂級", "reason": "極限詞"}, ...]
        無違規或不支援平台時回傳空 list。
    """
    if not text or platform not in PLATFORMS:
        return []

    hits: list[dict] = []
    seen: set[str] = set()
    for rule in _rules_for(platform):
        if rule.word in text and rule.word not in seen:
            hits.append({
                "word": rule.word,
                "suggest": rule.suggest,
                "reason": rule.reason,
            })
            seen.add(rule.word)
    return hits


def is_clean(text: str, platform: str) -> bool:
    """快速判斷一段文字在指定平台是否乾淨（無違規）。"""
    return len(scan(text, platform)) == 0

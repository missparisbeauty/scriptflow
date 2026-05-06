"""跨模組共用業務規則 — Phase 1。

提供：
  - classify_funnel_role(): 漏斗角色分類（seed / pull / harvest）
  - compute_similarity(): 內容與分類的關鍵字重疊比例（0-1）
  - compute_purchase_intent_density(): 導購意圖詞密度（0-1）

domain 層不可依賴 service / infra（architecture.md）。
"""

from __future__ import annotations

import re
from typing import Final

from domain import categories as _categories

# --- 漏斗角色 ---

FUNNEL_ROLES: Final = ("seed", "pull", "harvest")
"""三個漏斗角色：
  - seed:    種子，種草／品牌印象
  - pull:    拉新，引流／吸引點擊
  - harvest: 收割，轉換／成交
"""

# 同義詞映射（容許 service 傳遞中文/別名）
_FUNNEL_ALIASES: dict[str, str] = {
    "seed": "seed",
    "種子": "seed",
    "種草": "seed",
    "awareness": "seed",
    "pull": "pull",
    "拉新": "pull",
    "引流": "pull",
    "interest": "pull",
    "harvest": "harvest",
    "收割": "harvest",
    "轉換": "harvest",
    "conversion": "harvest",
    "purchase": "harvest",
}


def classify_funnel_role(label: str) -> str | None:
    """將輸入標籤正規化為三個漏斗角色之一。

    Args:
        label: 漏斗標籤，可為 seed/pull/harvest 或中文別名

    Returns:
        正規化後的角色名（"seed" / "pull" / "harvest"），無法辨識回傳 None
    """
    if not label:
        return None
    return _FUNNEL_ALIASES.get(label.strip().lower())


# --- 相似度計算 ---


def _tokenize(text: str) -> list[str]:
    """簡易斷詞：以空白與標點切，保留 2 字元以上的字串。

    後續可改用 jieba 等中文斷詞工具強化（Phase 7 優化項）。
    """
    if not text:
        return []
    parts = re.split(r"[\s,，。、；;:：!！?？\(\)（）\[\]【】\"'`~#@\-_]+", text)
    return [p for p in parts if len(p) >= 2]


def compute_similarity(content: str, category: str) -> float:
    """計算內容與分類的關鍵字重疊度。

    Args:
        content: 待評估的文字（標題、描述、貼文內容等）
        category: 分類名稱（如「髮品」）

    Returns:
        0-1 浮點數。0 表示無重疊，1 表示所有關鍵字都出現。
        分類不存在時回傳 0.0。
    """
    keywords = _categories.get_keywords(category)
    if not keywords or not content:
        return 0.0

    # 中文沒空白分隔，用子字串比對
    hit = sum(1 for kw in keywords if kw in content)
    similarity = hit / len(keywords)
    return min(1.0, max(0.0, similarity))


# --- 導購意圖密度 ---

_PURCHASE_INTENT_WORDS: Final[tuple[str, ...]] = (
    "限時", "限量", "折扣", "優惠", "特價", "下單", "搶購",
    "團購", "代購", "私訊", "DM", "下單連結", "限動",
    "私我", "聊聊", "問我", "領券", "領取", "點擊",
    "點我", "點連結", "點下方", "連結",
    "開賣", "首賣", "預購", "上架", "補貨",
)


def compute_purchase_intent_density(text: str) -> float:
    """偵測導購意圖詞密度。

    定義：(命中的詞數) / (預設詞庫長度)，並裁切到 [0, 1]。
    一個爆款若密度 ≥ 0.10，CrawlerService 會標 funnel_role=harvest。

    Args:
        text: 待評估文字

    Returns:
        0-1 浮點數
    """
    if not text:
        return 0.0
    hit = sum(1 for w in _PURCHASE_INTENT_WORDS if w in text)
    density = hit / len(_PURCHASE_INTENT_WORDS)
    return min(1.0, max(0.0, density))


# --- 預設門檻（CrawlerService 與 CandidateService 共用） ---

B_TRACK_SIMILARITY_THRESHOLD: Final = 0.80
"""B 軌相似度下限：相似度 ≥ 0.80 才視為合格的 B 軌候選。"""

PURCHASE_INTENT_HARVEST_THRESHOLD: Final = 0.10
"""導購意圖密度 ≥ 0.10 → funnel_role=harvest。"""

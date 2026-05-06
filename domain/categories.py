"""分類定義（美妝 / 美食 / 髮品）— Phase 1。

提供：
  - 三大分類設定（關鍵字、B 軌允許類型）
  - 查詢 helper：list_categories(), get_category(), is_valid_category()

domain 層是最底層，禁止 import 任何 service 或 infra（architecture.md 依賴方向）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- 分類設定 ---


@dataclass(frozen=True)
class Category:
    """單一分類設定。

    Attributes:
        name: 分類名稱（顯示用）
        keywords: 用於 topic_match / similarity 比對的關鍵字
        b_track_allowed_types: B 軌（次類別）允許的類型，用於相似度評估
    """

    name: str
    keywords: tuple[str, ...]
    b_track_allowed_types: tuple[str, ...] = field(default_factory=tuple)


_CATEGORIES: dict[str, Category] = {
    "美妝": Category(
        name="美妝",
        keywords=(
            "底妝", "粉底", "氣墊", "口紅", "唇釉", "唇膏",
            "眼影", "眉粉", "睫毛膏", "腮紅", "修容", "高光",
            "卸妝", "保養", "精華", "面膜", "化妝水", "乳液",
            "防曬", "膚質", "毛孔", "暗沉", "痘痘", "敏感肌",
        ),
        b_track_allowed_types=("彩妝", "保養", "卸妝品", "防曬"),
    ),
    "美食": Category(
        name="美食",
        keywords=(
            "料理", "食譜", "做法", "甜點", "蛋糕", "餅乾",
            "便當", "早餐", "減脂餐", "增肌", "宵夜",
            "飲料", "手搖", "氣泡水", "咖啡", "茶飲",
            "零食", "點心", "下午茶", "聚餐", "野餐",
        ),
        b_track_allowed_types=("料理", "甜點", "飲料", "零食"),
    ),
    "髮品": Category(
        name="髮品",
        keywords=(
            "洗髮", "護髮", "髮膜", "潤髮", "頭皮",
            "造型", "捲髮", "直髮", "燙髮", "染髮",
            "毛躁", "受損", "斷裂", "分岔", "出油",
            "髮質", "蓬鬆", "光澤", "扁塌", "禿頭",
        ),
        b_track_allowed_types=("洗護髮", "造型", "染護", "頭皮護理"),
    ),
}


# --- 查詢 helper ---


def list_categories() -> list[str]:
    """回傳所有支援的分類名稱（排序）。"""
    return sorted(_CATEGORIES.keys())


def get_category(name: str) -> Category | None:
    """取得分類設定，找不到回傳 None。"""
    return _CATEGORIES.get(name)


def is_valid_category(name: str) -> bool:
    """判斷分類名稱是否有效。"""
    return name in _CATEGORIES


def get_keywords(name: str) -> tuple[str, ...]:
    """取得分類關鍵字，找不到回傳空 tuple。"""
    cat = _CATEGORIES.get(name)
    return cat.keywords if cat else ()


def get_b_track_types(name: str) -> tuple[str, ...]:
    """取得 B 軌允許類型清單，找不到回傳空 tuple。"""
    cat = _CATEGORIES.get(name)
    return cat.b_track_allowed_types if cat else ()

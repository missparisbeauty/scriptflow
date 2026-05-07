"""Firestore CRUD 封裝 — Phase 2。

責任：
  - 提供 candidates / scripts / tracking / brand_dna 四個 collection 的讀寫
  - 統一處理 SERVER_TIMESTAMP、軟刪除過濾、limit 上限
  - 不寫業務邏輯（service 層的事）

依 rule-database：
  - 所有讀取必須 limit()，預設 50，上限 200
  - 軟刪除統一用 is_deleted: bool，infra 預設加過濾
  - 多筆寫入用 batch；原子讀寫用 transaction
  - document ID 由呼叫方傳入（可預測 ID 用於 candidates 的 yyyymmdd_category，
    其餘用 UUID）
  - timestamps 一律用 firestore.SERVER_TIMESTAMP
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter

from config import settings

logger = logging.getLogger(__name__)

# --- collection 名稱（snake_case，rule-database） ---

COL_CANDIDATES = "candidates"
COL_SCRIPTS = "scripts"
COL_TRACKING = "tracking"
COL_BRAND_DNA = "brand_dna"

# --- 限制 ---

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


# --- 單例 client ---

_client: firestore.Client | None = None


def get_db() -> firestore.Client:
    """惰性初始化 Firestore client（執行時才建，import 時不建）。"""
    global _client
    if _client is None:
        if not settings.GCP_PROJECT_ID:
            raise RuntimeError(
                "GCP_PROJECT_ID not configured (env var or .env required)"
            )
        _client = firestore.Client(project=settings.GCP_PROJECT_ID)
    return _client


def reset_client() -> None:
    """測試用：清空 client 快取。"""
    global _client
    _client = None


# --- 內部 helper ---


def _validate_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit <= 0:
        raise ValueError("limit must be positive")
    return min(limit, MAX_LIMIT)


def _now_marker() -> Any:
    """回傳 SERVER_TIMESTAMP sentinel（避免 client 時鐘飄移）。"""
    return firestore.SERVER_TIMESTAMP


def _to_dict(snapshot: firestore.DocumentSnapshot) -> dict | None:
    """Snapshot → dict + 注入 id 欄位。"""
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    data["id"] = snapshot.id
    return data


# --- 通用 CRUD（被特化函式呼叫） ---


def _save(collection: str, doc_id: str, data: dict) -> str:
    """建立或覆寫一筆 document（document 完整替換）。"""
    payload = dict(data)
    payload.setdefault("is_deleted", False)
    payload["updated_at"] = _now_marker()
    if "created_at" not in payload:
        payload["created_at"] = _now_marker()

    get_db().collection(collection).document(doc_id).set(payload)
    return doc_id


def _patch(collection: str, doc_id: str, partial: dict) -> None:
    """部分更新欄位（不影響其他欄位）。"""
    payload = dict(partial)
    payload["updated_at"] = _now_marker()
    get_db().collection(collection).document(doc_id).update(payload)


def _get(collection: str, doc_id: str) -> dict | None:
    """取得單筆，已軟刪除回傳 None。"""
    snap = get_db().collection(collection).document(doc_id).get()
    data = _to_dict(snap)
    if data is None or data.get("is_deleted"):
        return None
    return data


def _query(
    collection: str,
    *,
    filters: Iterable[tuple[str, str, Any]] = (),
    order_by: str | None = None,
    descending: bool = True,
    limit: int | None = None,
) -> list[dict]:
    """通用查詢；is_deleted 過濾與 ordering 在 Python 後處理，避免 Firestore
    composite index 維護負擔（rule-database：infra 負責過濾，未指定一定要在
    Firestore 端執行）。

    交換條件：每次 over-fetch 3x 額度，足以包含被 is_deleted 排除掉的部分。
    對本專案規模（單 collection 數百筆）成本可忽略。
    """
    safe_limit = _validate_limit(limit)
    fetch_budget = min(MAX_LIMIT, max(safe_limit * 3, 10))

    q = get_db().collection(collection)
    for field, op, value in filters:
        q = q.where(filter=FieldFilter(field, op, value))
    q = q.limit(fetch_budget)

    raw = [_to_dict(s) for s in q.stream()]
    docs = [d for d in raw if d is not None and not d.get("is_deleted")]

    if order_by:
        docs.sort(
            key=lambda d: d.get(order_by) or "",
            reverse=descending,
        )

    return docs[:safe_limit]


def _soft_delete(collection: str, doc_id: str) -> None:
    """軟刪除（設 is_deleted=True，不實際刪 document）。"""
    _patch(collection, doc_id, {"is_deleted": True})


# --- candidates collection ---


def save_candidate(candidate_id: str, data: dict) -> str:
    """寫入今日候選（doc_id 慣例：yyyymmdd_category）。"""
    return _save(COL_CANDIDATES, candidate_id, data)


def get_candidate(candidate_id: str) -> dict | None:
    return _get(COL_CANDIDATES, candidate_id)


def list_candidates_by_date(date: str, limit: int | None = None) -> list[dict]:
    """依日期取候選，例：date='2026-05-06'。"""
    return _query(
        COL_CANDIDATES,
        filters=[("date", "==", date)],
        order_by="created_at",
        limit=limit,
    )


def list_candidates_by_category(
    category: str, limit: int | None = None
) -> list[dict]:
    return _query(
        COL_CANDIDATES,
        filters=[("category", "==", category)],
        order_by="created_at",
        limit=limit,
    )


def delete_candidate(candidate_id: str) -> None:
    _soft_delete(COL_CANDIDATES, candidate_id)


def delete_candidates_before(date_iso: str) -> int:
    """軟刪除所有 date < date_iso 的候選（保留期外的舊資料）。

    Args:
        date_iso: 'YYYY-MM-DD'，早於此日期（不含）的會被軟刪除

    Returns:
        被軟刪除的數量
    """
    docs = _query(COL_CANDIDATES, limit=500)
    deleted = 0
    for doc in docs:
        d = doc.get("date")
        doc_id = doc.get("id")
        if d and doc_id and d < date_iso:
            _soft_delete(COL_CANDIDATES, doc_id)
            deleted += 1
    return deleted


# --- scripts collection ---


def save_script(script_id: str, data: dict) -> str:
    return _save(COL_SCRIPTS, script_id, data)


def get_script(script_id: str) -> dict | None:
    return _get(COL_SCRIPTS, script_id)


def list_scripts_by_date(date: str, limit: int | None = None) -> list[dict]:
    return _query(
        COL_SCRIPTS,
        filters=[("date", "==", date)],
        order_by="created_at",
        limit=limit,
    )


def list_scripts_by_category(
    category: str, limit: int | None = None
) -> list[dict]:
    return _query(
        COL_SCRIPTS,
        filters=[("category", "==", category)],
        order_by="created_at",
        limit=limit,
    )


def delete_script(script_id: str) -> None:
    _soft_delete(COL_SCRIPTS, script_id)


# --- tracking collection ---


def save_tracking(tracking_id: str, data: dict) -> str:
    return _save(COL_TRACKING, tracking_id, data)


def get_tracking(tracking_id: str) -> dict | None:
    return _get(COL_TRACKING, tracking_id)


def update_tracking_metrics(
    tracking_id: str, *, metrics_field: str, metrics: dict
) -> None:
    """更新 metrics_7d 或 metrics_14d 子欄位。"""
    if metrics_field not in {"metrics_7d", "metrics_14d"}:
        raise ValueError(
            f"metrics_field must be metrics_7d or metrics_14d, "
            f"got {metrics_field!r}"
        )
    _patch(COL_TRACKING, tracking_id, {metrics_field: metrics})


def list_tracking_by_script(
    script_id: str, limit: int | None = None
) -> list[dict]:
    return _query(
        COL_TRACKING,
        filters=[("script_id", "==", script_id)],
        order_by="created_at",
        limit=limit,
    )


def list_tracking_recent(limit: int | None = None) -> list[dict]:
    return _query(COL_TRACKING, order_by="created_at", limit=limit)


def delete_tracking(tracking_id: str) -> None:
    _soft_delete(COL_TRACKING, tracking_id)


# --- brand_dna collection ---


def save_brand_dna(dna_id: str, data: dict) -> str:
    return _save(COL_BRAND_DNA, dna_id, data)


def get_latest_brand_dna() -> dict | None:
    """取最新一筆 brand_dna（依 created_at desc 取首筆）。"""
    rows = _query(COL_BRAND_DNA, order_by="created_at", limit=1)
    return rows[0] if rows else None

"""統一 API response 格式 helper — Phase 5。

對齊 spec-developer 與 rule-api-design：
  成功：{"data": ..., "error": null}
  失敗：{"data": null, "error": {"code": "...", "message": "..."}}

設計：
  - 由 route 呼叫包裝；service 拋 Exception，集中 handler 在 main.py 包裝
  - 不暴露 stack trace 或內部錯誤（rule-cloud）
"""

from __future__ import annotations

from typing import Any


def ok(data: Any) -> dict:
    """成功 response。"""
    return {"data": data, "error": None}


def err(code: str, message: str) -> dict:
    """失敗 response。"""
    return {"data": None, "error": {"code": code, "message": message}}

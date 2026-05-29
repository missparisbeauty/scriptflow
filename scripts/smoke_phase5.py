"""Phase 5 smoke test：完整 API 端到端測試（用 TestClient + mocked firestore）。

需要環境變數：
  SF_SESSION_SECRET (≥32 chars)
  SF_ADMIN_PASSWORD
  SCHEDULER_ENABLED=false（避免測試啟動排程）
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 用一個簡易的 in-memory fake firestore
_store: dict[str, dict] = {}


def _fake_save_candidate(cid, data):
    _store["candidate:" + cid] = data
    return cid


def _fake_get_candidate(cid):
    return _store.get("candidate:" + cid)


def _fake_list_candidates_by_date(date, limit=None):
    return [
        v
        for k, v in _store.items()
        if k.startswith("candidate:") and v.get("date") == date
    ]


def _fake_save_script(sid, data):
    _store["script:" + sid] = data
    return sid


def _fake_get_script(sid):
    return _store.get("script:" + sid)


def _fake_save_tracking(tid, data):
    _store["tracking:" + tid] = data
    return tid


def _fake_get_tracking(tid):
    return _store.get("tracking:" + tid)


def _fake_list_tracking_recent(limit=None):
    return [v for k, v in _store.items() if k.startswith("tracking:")]


def _fake_save_brand_dna(did, data):
    _store["dna:" + did] = data
    return did


# Patch infra.firestore module-level functions
_PATCHES = [
    patch("infra.firestore.save_candidate", side_effect=_fake_save_candidate),
    patch("infra.firestore.get_candidate", side_effect=_fake_get_candidate),
    patch(
        "infra.firestore.list_candidates_by_date",
        side_effect=_fake_list_candidates_by_date,
    ),
    patch("infra.firestore.save_script", side_effect=_fake_save_script),
    patch("infra.firestore.get_script", side_effect=_fake_get_script),
    patch("infra.firestore.save_tracking", side_effect=_fake_save_tracking),
    patch("infra.firestore.get_tracking", side_effect=_fake_get_tracking),
    patch(
        "infra.firestore.list_tracking_recent",
        side_effect=_fake_list_tracking_recent,
    ),
    patch("infra.firestore.save_brand_dna", side_effect=_fake_save_brand_dna),
]
for p in _PATCHES:
    p.start()

from fastapi.testclient import TestClient

from main import app
from modules.auth.middleware import COOKIE_NAME

client = TestClient(app)


def _check(label, resp, expect_status, *, expect_data_key=None, expect_err_code=None):
    body = resp.json() if resp.headers.get("content-type", "").startswith(
        "application/json"
    ) else None
    ok = resp.status_code == expect_status
    if expect_err_code and body:
        ok = ok and body.get("error", {}).get("code") == expect_err_code
    if expect_data_key and body:
        ok = ok and (
            isinstance(body.get("data"), dict)
            and expect_data_key in body["data"]
        )
    mark = "[OK]" if ok else "[FAIL]"
    print(
        f"  {mark} {label}: {resp.status_code}"
        + (
            f" code={body.get('error', {}).get('code')}"
            if body and body.get("error")
            else ""
        )
    )
    assert ok, f"FAIL {label}: status={resp.status_code} body={body}"


# === 1. 公開 /health ===
print("=== 1. 公開 ===")
_check("GET /health", client.get("/health"), 200)


# === 2. 無 session 統一回 401 ===
print()
print("=== 2. 無 session ===")
for path in (
    "/api/v1/health",
    "/api/v1/candidates",
    "/api/v1/script/generate",
    "/api/v1/tracking/dna",
):
    method = "POST" if "generate" in path else "GET"
    if method == "POST":
        r = client.post(path, json={})
    else:
        r = client.get(path)
    _check(f"{method} {path}", r, 401, expect_err_code="UNAUTHORIZED")


# === 3. 登入流程 ===
print()
print("=== 3. 登入 ===")
r = client.post("/api/v1/auth/login", json={"password": "wrong"})
_check("login wrong pwd", r, 401, expect_err_code="AUTH_FAILED")

import os

correct_pwd = os.environ.get("SF_ADMIN_PASSWORD", "")
r = client.post("/api/v1/auth/login", json={"password": correct_pwd})
_check("login correct pwd", r, 200, expect_data_key="user_id")
cookie = r.cookies.get(COOKIE_NAME)
assert cookie, "no session cookie issued"
print(f"  session cookie issued (len={len(cookie)})")


# 帶 cookie 重建 client
client_auth = TestClient(app, cookies={COOKIE_NAME: cookie})


# === 4. /api/v1/health 有 session ===
print()
print("=== 4. 有 session ===")
r = client_auth.get("/api/v1/health")
_check("GET /api/v1/health", r, 200, expect_data_key="user")


# === 5. 候選 (沒資料 → CANDIDATES_NOT_READY) ===
print()
print("=== 5. candidates ===")
r = client_auth.get("/api/v1/candidates")
_check(
    "GET /candidates (no data)",
    r,
    409,
    expect_err_code="CANDIDATES_NOT_READY",
)


# === 6. 觸發爬取 ===
print()
print("=== 6. crawler trigger ===")
r = client_auth.post(
    "/api/v1/crawler/trigger",
    json={"category": "髮品"},
)
_check("POST /crawler/trigger", r, 200, expect_data_key="candidate_id")
candidate_id = r.json()["data"]["candidate_id"]
print(f"  candidate_id: {candidate_id}")


# === 7. candidates 現在有資料 ===
print()
print("=== 7. candidates again ===")
r = client_auth.get("/api/v1/candidates", params={"category": "髮品"})
_check("GET /candidates (has data)", r, 200)


# === 8. script/generate ===
print()
print("=== 8. script generate ===")
r = client_auth.post(
    "/api/v1/script/generate",
    json={"candidate_ids": [candidate_id], "category": "髮品"},
)
_check("POST /script/generate", r, 200, expect_data_key="script_id")
script_id = r.json()["data"]["script_id"]
versions = ["threads_post", "threads_reel", "ig_reels"]
data = r.json()["data"]
for v in versions:
    assert v in data, f"missing {v}"
    assert "cta_variants" in data[v]
    assert len(data[v]["cta_variants"]) == 3
    assert "compliance" in data[v]
print(f"  3 versions OK, script_id: {script_id}")


# === 9. storyboard ===
print()
print("=== 9. storyboard ===")
r = client_auth.post(
    "/api/v1/storyboard/generate",
    json={"script_id": script_id, "platform": "ig_reels"},
)
_check("POST /storyboard/generate", r, 200, expect_data_key="storyboard_id")
sb_data = r.json()["data"]
assert len(sb_data["scenes"]) == 5
print(f"  storyboard with {len(sb_data['scenes'])} scenes")
print(
    f"  image_data_url present: "
    f"{all('image_data_url' in s for s in sb_data['scenes'])}"
)


# === 10. tracking ===
print()
print("=== 10. tracking ===")
r = client_auth.post(
    "/api/v1/tracking",
    json={
        "script_id": script_id,
        "platform": "ig_reels",
        "publish_url": "https://www.instagram.com/reel/abc",
    },
)
_check("POST /tracking", r, 200, expect_data_key="tracking_id")

# DNA 不足
r = client_auth.get("/api/v1/tracking/dna")
_check("GET /tracking/dna (insufficient)", r, 409, expect_err_code="INSUFFICIENT_DATA")


# === 11. scheduler status ===
print()
print("=== 11. scheduler status ===")
r = client_auth.get("/api/v1/scheduler/status")
_check("GET /scheduler/status", r, 200, expect_data_key="enabled")


# === 12. logout + 再呼叫 ===
print()
print("=== 12. logout ===")
r = client_auth.post("/api/v1/auth/logout")
_check("POST /auth/logout", r, 200)


# === 13. validation error 也走統一格式 ===
print()
print("=== 13. validation ===")
r = client_auth.post(
    "/api/v1/script/generate",
    json={"candidate_ids": [], "category": "x"},
)
_check("validation empty list", r, 400, expect_err_code="VALIDATION_ERROR")


print()
print("Phase 5 smoke test PASS")

# 清理 patches
for p in _PATCHES:
    p.stop()

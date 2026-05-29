"""Smoke checks for Xiaohongshu preview behavior.

Run from repo root:
    python scripts/smoke_xhs_preview.py

This does not call Apify. It patches the crawler and Firestore cache so the
route, URL sanitization, actor-input selection, and CSP behavior can be checked
without credentials.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("CRAWLER_BACKEND", "mock")
os.environ.setdefault("GCP_PROJECT_ID", "seo-mpb")
os.environ.setdefault("SF_SESSION_SECRET", "local-test-secret-local-test-secret")
os.environ.setdefault("SF_ADMIN_PASSWORD", "localdev")

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from infra import crawler_client
from infra.crawler_client import _build_xhs_preview_input
from main import app
from modules.auth.middleware import COOKIE_NAME
from modules.candidates.service import (
    _hydrate_xhs_previews,
    _sanitize_xhs_note_url,
    get_xhs_preview,
)


NOTE_ID = "69f62f2a000000003501e312"
BASE_URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}"
TOKEN_URL = f"{BASE_URL}?xsec_token=abc&foo=drop&xsec_source=pc_feed"
SANITIZED_TOKEN_URL = f"{BASE_URL}?xsec_token=abc&xsec_source=pc_feed"
PROXY_CN = {"useApifyProxy": True, "apifyProxyCountry": "CN"}


def _assert(label: str, condition: bool) -> None:
    mark = "[OK]" if condition else "[FAIL]"
    print(f"  {mark} {label}")
    assert condition, label


def check_sanitizer() -> None:
    print("=== URL sanitizer ===")
    _assert("bare explore URL allowed", _sanitize_xhs_note_url(BASE_URL) == BASE_URL)
    _assert(
        "only preview query params kept",
        _sanitize_xhs_note_url(TOKEN_URL) == SANITIZED_TOKEN_URL,
    )
    _assert(
        "non-xhs host blocked",
        _sanitize_xhs_note_url(f"https://evil.example/explore/{NOTE_ID}") is None,
    )
    _assert(
        "wrong path blocked",
        _sanitize_xhs_note_url(f"https://www.xiaohongshu.com/user/{NOTE_ID}") is None,
    )


def check_actor_inputs() -> None:
    print()
    print("=== Actor inputs ===")
    _assert(
        "dltik preview actor uses post mode",
        _build_xhs_preview_input("dltik/rednote-xiaohongshu-scraper", BASE_URL)
        == {"mode": "post", "noteUrls": [BASE_URL], "proxyConfiguration": PROXY_CN},
    )
    with patch.object(crawler_client, "XHS_COOKIES", "a=b; c=d"):
        _assert(
            "dltik preview actor forwards optional cookies",
            _build_xhs_preview_input("dltik/rednote-xiaohongshu-scraper", BASE_URL)
            == {
                "mode": "post",
                "noteUrls": [BASE_URL],
                "proxyConfiguration": PROXY_CN,
                "cookiesString": "a=b; c=d",
            },
        )
    _assert(
        "zhorex preview actor uses post_details mode",
        _build_xhs_preview_input("zhorex/rednote-xiaohongshu-scraper", BASE_URL)
        == {"mode": "post_details", "postUrls": [BASE_URL], "proxyConfiguration": PROXY_CN},
    )


def check_service_cache_and_fallback() -> None:
    print()
    print("=== Service cache/fallback ===")
    cached = {"title": "cached", "content": "cached body", "images": [], "author": ""}
    empty_cached = {"title": "empty", "content": "", "images": [], "author": ""}
    fetched = {"title": "fetched", "content": "fetched body", "images": [], "author": ""}

    with patch("infra.firestore.get_xhs_preview_cache", return_value=cached), patch(
        "infra.crawler_client.fetch_xhs_post_details"
    ) as fetch:
        _assert("cache hit returned", get_xhs_preview(BASE_URL)["title"] == "cached")
        _assert("cache hit skips Apify fallback", fetch.call_count == 0)

    with patch("infra.firestore.get_xhs_preview_cache", return_value=empty_cached), patch(
        "infra.crawler_client.fetch_xhs_post_details", return_value=fetched
    ) as fetch, patch("infra.firestore.save_xhs_preview_cache") as save:
        _assert("cache miss fetches fallback", get_xhs_preview(TOKEN_URL)["title"] == "fetched")
        _assert("fallback gets sanitized URL", fetch.call_args.args[0] == SANITIZED_TOKEN_URL)
        _assert("fallback result saved to cache", save.call_args.args[0] == NOTE_ID)

    doc = {
        "items": [
            {
                "platform": "xiaohongshu",
                "source_url": BASE_URL,
                "title": "candidate",
            }
        ]
    }
    with patch("infra.firestore.get_xhs_preview_cache", return_value=cached):
        _hydrate_xhs_previews(doc)
        _assert("candidate list hydrates cached preview", doc["items"][0]["preview"]["title"] == "cached")


def check_route_and_csp() -> None:
    print()
    print("=== Route/CSP ===")
    seen = {}
    fetched = {
        "title": "ok title",
        "content": "ok content",
        "images": ["https://example.com/a.jpg"],
        "author": "tester",
        "likes": 1,
        "comments": 2,
        "collects": 3,
    }

    def fake_fetch(url: str) -> dict:
        seen["url"] = url
        return fetched

    with patch("infra.firestore.get_xhs_preview_cache", return_value=None), patch(
        "infra.crawler_client.fetch_xhs_post_details", side_effect=fake_fetch
    ):
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={"password": "localdev"})
            _assert("login succeeds", login.status_code == 200)
            cookie = login.cookies.get(COOKIE_NAME)
            _assert("session cookie issued", bool(cookie))

            preview = client.get("/api/v1/candidates/xhs-preview", params={"url": TOKEN_URL})
            _assert("preview route succeeds", preview.status_code == 200)
            _assert("preview payload returned", preview.json()["data"]["title"] == "ok title")
            _assert("route passes sanitized URL", seen["url"] == SANITIZED_TOKEN_URL)

            index = client.get("/")
            csp = index.headers.get("content-security-policy", "")
            _assert("CSP allows HTTPS images", "img-src 'self' data: https:" in csp)


if __name__ == "__main__":
    check_sanitizer()
    check_actor_inputs()
    check_service_cache_and_fallback()
    check_route_and_csp()
    print()
    print("XHS preview smoke checks passed.")

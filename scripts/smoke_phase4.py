"""Phase 4 smoke test：5 個 service 加 mock firestore。一次性測試腳本。"""

from unittest.mock import patch

from domain.exceptions import (
    CandidatesNotReady,
    InsufficientData,
    InvalidInput,
    ResourceNotFound,
)


# ===== CrawlerService =====
print("=== CrawlerService ===")
from modules.crawler.service import run_daily_crawl

saved: dict = {}


def fake_save_candidate(cid, data):
    saved["id"] = cid
    saved["data"] = data
    return cid


with patch(
    "modules.crawler.service.fs.save_candidate", side_effect=fake_save_candidate
):
    result = run_daily_crawl("髮品", strategy="balanced")

assert result["candidate_id"].endswith("_髮品"), result["candidate_id"]
assert result["topic"]
assert 0 <= result["topic_concentration"] <= 1
assert len(result["items"]) == 3
for i, item in enumerate(result["items"], start=1):
    assert item["rank"] == i
    assert item["funnel_role"] in ("seed", "pull", "harvest")
    assert 0 <= item["topic_match"] <= 1
    assert 0 <= item["purchase_intent_density"] <= 1
print(f"  candidate_id: {result['candidate_id']}")
print(f"  topic: {result['topic'][:30]}, concentration: {result['topic_concentration']}")
print(
    "  3 items rank=1,2,3 funnel_roles: "
    f"{[it['funnel_role'] for it in result['items']]}"
)
print(f"  saved: id={saved['id']}, items={len(saved['data']['items'])}")

try:
    run_daily_crawl("xxx")
except InvalidInput:
    print("  invalid category rejected OK")


# ===== CandidateService =====
print()
print("=== CandidateService ===")
from modules.candidates.service import get_candidates, get_today_candidates

with patch("modules.candidates.service.fs.list_candidates_by_date", return_value=[]):
    try:
        get_today_candidates("balanced")
    except CandidatesNotReady as e:
        print(f"  no data -> CandidatesNotReady OK (code={e.error_code})")

fake_doc = {
    "id": "20260506_髮品",
    "date": "2026-05-06",
    "category": "髮品",
    "items": [{"rank": 1}],
}
with patch(
    "modules.candidates.service.fs.list_candidates_by_date", return_value=[fake_doc]
):
    r = get_today_candidates("balanced")
    assert "items" in r
    print(f"  list mode OK: {len(r['items'])} doc(s)")

with patch("modules.candidates.service.fs.get_candidate", return_value=fake_doc):
    r = get_today_candidates("balanced", category="髮品")
    assert r["category"] == "髮品"
    print(f"  category mode OK: {r['category']}")

with patch(
    "modules.candidates.service.fs.get_candidate",
    side_effect=[fake_doc, None, fake_doc],
):
    docs = get_candidates(["a", "b", "c"])
    assert len(docs) == 2
    print(f"  get_candidates skips None: {len(docs)}/3")


# ===== ScriptService =====
print()
print("=== ScriptService ===")
from modules.script.service import generate as script_generate

candidate_doc = {
    "id": "20260506_髮品",
    "topic": "受損髮質修護",
    "items": [
        {
            "platform": "xiaohongshu",
            "title": "頭髮乾燥毛躁髮膜實測",
            "engagement": 282000,
            "funnel_role": "pull",
        },
        {
            "platform": "douyin",
            "title": "髮膜對比實測",
            "engagement": 412000,
            "funnel_role": "harvest",
        },
    ],
}
script_saved: dict = {}


def fake_save_script(sid, data):
    script_saved["id"] = sid
    script_saved["data"] = data
    return sid


with patch(
    "modules.script.service.candidates_service.get_candidates",
    return_value=[candidate_doc],
), patch(
    "modules.script.service.fs.save_script", side_effect=fake_save_script
):
    result = script_generate(["20260506_髮品"], "髮品")

assert result["script_id"].startswith("script_"), result["script_id"]
for tpl in ("threads_post", "threads_reel", "ig_reels"):
    assert tpl in result
    assert "cta_variants" in result[tpl]
    assert "compliance" in result[tpl]
    assert len(result[tpl]["cta_variants"]) == 3
print(f"  script_id: {result['script_id']}")
print(
    "  CTA per version: "
    f"{[len(result[v]['cta_variants']) for v in ('threads_post','threads_reel','ig_reels')]}"
)
print(
    "  compliance hits per version: "
    f"{[len(result[v]['compliance']) for v in ('threads_post','threads_reel','ig_reels')]}"
)

try:
    script_generate([], "髮品")
except InvalidInput:
    print("  empty ids rejected OK")


# ===== StoryboardService =====
print()
print("=== StoryboardService ===")
from modules.storyboard.service import generate as sb_generate

fake_script = {
    "id": "script_xxx",
    "ig_reels": {
        "segments": [
            {"time": "0-10s", "scene": "hook", "voiceover": "v1", "sfx": "s1"},
            {"time": "10-30s", "scene": "pain", "voiceover": "v2", "sfx": "s2"},
            {"time": "30-50s", "scene": "product", "voiceover": "v3", "sfx": "s3"},
            {"time": "50-60s", "scene": "cta", "voiceover": "v4", "sfx": "s4"},
        ],
    },
}
with patch(
    "modules.storyboard.service.script_service.get_script", return_value=fake_script
):
    sb = sb_generate("script_xxx", "ig_reels")
assert sb["storyboard_id"].startswith("sb_")
assert len(sb["scenes"]) == 5
exposure_50 = sb["scenes"][2]["product_exposure"]  # 第 3 鏡（index=3/5=0.6）→ product_focus
print(f"  storyboard_id: {sb['storyboard_id']}")
print(f"  scenes count: {len(sb['scenes'])} (4 -> 5 expansion)")
print(f"  scene 3 (~50% pos) exposure: {exposure_50}")
print(
    "  images mocked OK: "
    f"{all(s['image_status'] == 'ok' for s in sb['scenes'])}"
)

try:
    sb_generate("xxx", "youtube")
except InvalidInput:
    print("  bad platform rejected OK")

with patch(
    "modules.storyboard.service.script_service.get_script", return_value=None
):
    try:
        sb_generate("missing", "ig_reels")
    except ResourceNotFound:
        print("  missing script -> ResourceNotFound OK")


# ===== TrackingService =====
print()
print("=== TrackingService ===")
from modules.tracking.service import compute_dna, save_tracking

try:
    save_tracking("script_x", "ig_reels", "not-a-url")
except InvalidInput:
    print("  bad URL rejected OK")

with patch("modules.tracking.service.fs.save_tracking", return_value="tracking_xxx"):
    tid = save_tracking("script_x", "ig_reels", "https://www.instagram.com/reel/abc")
    assert tid.startswith("tracking_")
    print(f"  saved tracking: {tid}")

with patch("modules.tracking.service.fs.list_tracking_recent", return_value=[]):
    try:
        compute_dna()
    except InsufficientData as e:
        print(f"  empty -> InsufficientData OK (code={e.error_code})")

fake_tracks = [
    {
        "script_id": f"s{i}",
        "metrics_7d": {
            "views": 1000,
            "completion_rate": 0.7,
            "ctr": 0.05,
            "conversions": 10,
        },
    }
    for i in range(6)
]
fake_scripts = [{"id": f"s{i}", "category": "髮品"} for i in range(6)]
with patch(
    "modules.tracking.service.fs.list_tracking_recent", return_value=fake_tracks
), patch(
    "modules.tracking.service.script_service.get_script", side_effect=fake_scripts
), patch(
    "modules.tracking.service.fs.save_brand_dna", return_value="dna_xxx"
):
    dna = compute_dna()
assert "best_opening" in dna and "best_cta" in dna and "best_product_timing" in dna
assert dna["sample_count"] == 6
print(f"  dna_id: {dna['id']}, samples: {dna['sample_count']}")

print()
print("Phase 4 smoke test PASS")

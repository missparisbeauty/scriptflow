"""StoryboardService — Phase 4。

職責（spec-developer F4）：
  - 從 scripts 取腳本（透過 ScriptService.get_script，rule-module-isolation）
  - 產 5 鏡頭分鏡列（從腳本 4 段 segments 拆出第 5 鏡）
  - 呼叫 image_gen_client 產示意圖（失敗回 None，不中斷）
  - 產品露出策略：50% 位置主推產品

不擁有獨立 collection（storyboard 在運行時生成、按需匯出）。
"""

from __future__ import annotations

import logging
import uuid

from domain.exceptions import InvalidInput, ResourceNotFound
from infra import image_gen_client
from modules.script import service as script_service

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ("threads_reel", "ig_reels")
NUM_SCENES = 5  # spec F4


# --- 對外 ---


def generate(script_id: str, platform: str) -> dict:
    """從 scripts 取腳本，產 5 鏡頭分鏡列。

    完成條件：StoryboardService.generate(script_id, 'ig_reels') → 5 鏡頭
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise InvalidInput(
            f"platform must be one of {SUPPORTED_PLATFORMS}",
            platform=platform,
        )

    # 跨模組讀 scripts → 走 ScriptService.get_script（rule-module-isolation）
    script_doc = script_service.get_script(script_id)
    if not script_doc:
        raise ResourceNotFound(
            f"script not found: {script_id}", script_id=script_id
        )

    version = script_doc.get(platform)
    if not version:
        raise InvalidInput(
            f"script has no {platform} version",
            script_id=script_id,
            platform=platform,
        )

    segments = version.get("segments") or []
    scenes = _expand_to_scenes(segments)

    storyboard_id = f"sb_{uuid.uuid4().hex[:8]}"
    enriched: list[dict] = []
    for i, scene in enumerate(scenes, start=1):
        prompt = _scene_to_image_prompt(scene)
        img_bytes = image_gen_client.generate_storyboard_image(prompt)
        enriched.append(
            {
                "index": i,
                "time": scene.get("time", ""),
                "scene": scene.get("scene", ""),
                "voiceover": scene.get("voiceover", ""),
                "sfx": scene.get("sfx", ""),
                "product_exposure": _product_exposure_strategy(i, NUM_SCENES),
                "image_bytes": img_bytes,
                "image_status": "ok" if img_bytes else "placeholder",
            }
        )

    logger.info(
        "storyboard.generated id=%s script=%s scenes=%d",
        storyboard_id,
        script_id,
        len(enriched),
    )
    return {
        "storyboard_id": storyboard_id,
        "script_id": script_id,
        "platform": platform,
        "scenes": enriched,
    }


# --- 內部 ---


def _expand_to_scenes(segments: list[dict]) -> list[dict]:
    """4 段 → 5 鏡頭：把第 2 段（痛點）拆成兩個畫面。"""
    if len(segments) >= NUM_SCENES:
        return list(segments[:NUM_SCENES])
    if len(segments) == 4:
        a, b, c, d = segments
        return [
            a,
            {**b, "scene": (b.get("scene") or "") + " — 前段"},
            {**b, "scene": (b.get("scene") or "") + " — 後段"},
            c,
            d,
        ]
    # 不足 4 段：補 placeholder 至 5 鏡
    out = list(segments)
    while len(out) < NUM_SCENES:
        out.append({"scene": "[placeholder]", "voiceover": "", "sfx": ""})
    return out


def _scene_to_image_prompt(scene: dict) -> str:
    """用 scene 描述組圖像 prompt。

    註：這裡的字串會送進 image_gen_client，prompt 是 LLM 已產出的（service 端
    已過合規掃描）。仍保守只塞 scene + voiceover，不放使用者直傳輸入。
    """
    parts = [scene.get("scene") or "", scene.get("voiceover") or ""]
    return " | ".join(p for p in parts if p)


def _product_exposure_strategy(index: int, total: int) -> str:
    """產品露出策略（spec F4：50% 位置主推產品）。"""
    pos = index / total
    if 0.4 < pos <= 0.6:
        return "product_focus"
    if pos <= 0.2:
        return "hook_no_product"
    if pos > 0.8:
        return "cta"
    return "supporting"

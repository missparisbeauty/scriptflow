"""OpenAI 圖像 API 封裝（gpt-image-1）— Phase 3。

責任：
  - generate_storyboard_image(prompt) 失敗回 None（spec F4：不中斷流程）
  - 跟 llm_client 共用同一把 OPENAI_API_KEY
  - 沒設 key 或 IMAGE_BACKEND=mock 時走 mock（回 1×1 PNG）

設計：
  - 失敗統一回 None、不拋 exception，由 service 層決定 placeholder 策略
  - timeout 比文字長（圖像生成慢），預設 90s
  - 不 log prompt 完整內容（rule-ai-llm）
"""

from __future__ import annotations

import base64
import logging
import os

from config import settings

logger = logging.getLogger(__name__)

# --- 設定 ---

MODEL_NAME = "gpt-image-1"
DEFAULT_SIZE = "1024x1024"
ALLOWED_SIZES = ("1024x1024", "1024x1536", "1536x1024")
DEFAULT_TIMEOUT_SECONDS = 90  # 圖像 API 慢
DEFAULT_QUALITY = "medium"  # gpt-image-1 quality 選項

# 67 bytes 合法 1×1 透明 PNG（mock 用）
_MOCK_PNG: bytes = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


# --- 對外 API ---


def is_mock() -> bool:
    if os.getenv("IMAGE_BACKEND", "").lower() == "mock":
        return True
    return not settings.OPENAI_API_KEY


def generate_storyboard_image(
    prompt: str,
    *,
    size: str = DEFAULT_SIZE,
) -> bytes | None:
    """生成單張分鏡示意圖。

    Args:
        prompt: 場景描述文字（service 層應已淨化過）
        size: 解析度（必須在 ALLOWED_SIZES 內）

    Returns:
        PNG bytes（成功），或 None（失敗、size 違規、prompt 空）。
        spec F4 要求：失敗不中斷流程。
    """
    if not prompt or not prompt.strip():
        return None
    if size not in ALLOWED_SIZES:
        logger.warning("image_gen invalid size=%s", size)
        return None

    if is_mock():
        return _MOCK_PNG

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        resp = client.images.generate(
            model=MODEL_NAME,
            prompt=prompt,
            size=size,
            n=1,
            quality=DEFAULT_QUALITY,
        )
        item = resp.data[0]
        # gpt-image-1 預設回 b64_json
        b64 = getattr(item, "b64_json", None)
        if b64:
            return base64.b64decode(b64)
        # fallback：若回 URL，用 httpx 抓圖
        url = getattr(item, "url", None)
        if url:
            return _fetch_url(url)
        logger.warning("image_gen empty response")
        return None
    except Exception as e:
        # spec F4：失敗不中斷流程
        logger.warning("image_gen failed err=%s", type(e).__name__)
        return None


# --- 內部 ---


def _fetch_url(url: str) -> bytes | None:
    """從 OpenAI 回的 URL 抓 PNG。仍封裝為「失敗回 None」。"""
    try:
        import httpx

        r = httpx.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.warning("image_gen fetch url failed err=%s", type(e).__name__)
        return None

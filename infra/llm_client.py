"""OpenAI 文字 API 封裝（GPT-5-mini）— Phase 3。

責任：
  - 統一 API call 入口（含重試、timeout、token 上限）
  - 不直接拼 prompt（由 service 層或 domain.prompts 組好傳入）
  - API key 只在這層讀取（rule-cloud / rule-ai-llm）
  - 沒設 OPENAI_API_KEY 或 LLM_BACKEND=mock 時走 mock 模式

公開 API（spec-developer 指定）：
  - generate_script(system_prompt, user_prompt, ...) → str
  - scan_compliance(text, platform) → list[dict]
  - compute_dna(samples) → dict

設計參考 rule-ai-llm：
  - System / user prompt 分離（caller 傳兩個參數）
  - max_completion_tokens 上限避免 token 耗盡
  - API key 只從 settings 讀取，不接受 client 傳入
  - log 不寫 prompt 完整內容、不寫 response、不寫 API key
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

# --- 設定 ---

MODEL_NAME = "gpt-5-mini"
# GPT-5-mini 是 reasoning model，內部思考也會消耗 token。
# 需給足空間：reasoning tokens + 實際輸出 tokens 都從 max_completion_tokens 扣。
# 觀測：reasoning 約吃 2000-3000，輸出腳本約 1000-1500 → 預留 8000 安全邊際。
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TIMEOUT_SECONDS = 90  # reasoning model 較慢，timeout 也加長
MAX_RETRIES = 2  # spec F3：「最多重試 2 次」
DNA_MIN_SAMPLES = 5  # spec F6：< 5 支 → INSUFFICIENT_DATA

# --- 成本護欄（rule-ai-llm：LLM API 成本控制）---
# gpt-5-mini 估算定價（USD per 1M tokens）
_COST_INPUT_PER_1M = 0.15
_COST_OUTPUT_PER_1M = 0.60
# 每次 LLM 呼叫估算上限，超過即拒絕（0 = 不限）
MAX_COST_PER_CALL_USD: float = float(os.getenv("LLM_MAX_COST_USD", "0.50"))


# --- 對外 API ---


def is_mock() -> bool:
    """是否走 mock 模式（沒 key 或顯式設定）。"""
    if os.getenv("LLM_BACKEND", "").lower() == "mock":
        return True
    return not settings.OPENAI_API_KEY


def generate_script(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    response_format: dict | None = None,
) -> str:
    """呼叫 GPT-5-mini，回傳 raw text response。

    Args:
        system_prompt: 由 domain.prompts.build_system_prompt() 組好
        user_prompt: 由 domain.prompts.build_prompt() 組好
        max_tokens: 輸出 token 上限（防 cost 失控，rule-ai-llm）
        response_format: 例 {"type": "json_object"} 強制 JSON 輸出

    Raises:
        ValueError: prompt 為空
        RuntimeError: 三次嘗試後仍失敗（service 應 catch 後回 SCRIPT_GENERATION_FAILED）
    """
    if not system_prompt or not user_prompt:
        raise ValueError("system_prompt and user_prompt must be non-empty")

    if is_mock():
        return _mock_generate_script(user_prompt)
    return _real_generate_script(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        response_format=response_format,
    )


def scan_compliance(text: str, platform: str) -> list[dict]:
    """LLM 二次合規掃描（補 domain.compliance_rules 的硬編碼禁詞）。

    輸出格式對齊 domain.compliance_rules.scan()：
        [{"word": "...", "suggest": "...", "reason": "..."}]
    """
    if not text:
        return []
    if is_mock():
        return _mock_scan_compliance(text, platform)
    return _real_scan_compliance(text, platform)


def compute_dna(samples: list[dict]) -> dict:
    """從成效樣本推斷品牌爆款 DNA。

    Args:
        samples: list of tracking + script 整合樣本

    Returns:
        {"best_opening": {...}, "best_cta": {...}, "best_product_timing": {...}}

    Raises:
        ValueError: samples 數量 < DNA_MIN_SAMPLES（service 層 catch → INSUFFICIENT_DATA）
    """
    if len(samples) < DNA_MIN_SAMPLES:
        raise ValueError(
            f"INSUFFICIENT_DATA: need >= {DNA_MIN_SAMPLES} samples, "
            f"got {len(samples)}"
        )
    if is_mock():
        return _mock_compute_dna(samples)
    return _real_compute_dna(samples)


# --- 成本估算與護欄 ---


def _estimate_cost(prompt_tokens: int, max_output_tokens: int) -> float:
    """估算單次 LLM 呼叫費用（USD）。

    使用字元數 ÷ 4 估算 token 數（英文約 4 char/token；中文約 1.5 char/token，
    取平均 3 char/token 偏保守，確保護欄不會低估）。
    """
    input_cost = (prompt_tokens / 1_000_000) * _COST_INPUT_PER_1M
    output_cost = (max_output_tokens / 1_000_000) * _COST_OUTPUT_PER_1M
    return input_cost + output_cost


def _check_cost_guard(system_prompt: str, user_prompt: str, max_tokens: int) -> None:
    """估算費用，超過 MAX_COST_PER_CALL_USD 時拋出 RuntimeError。

    設 LLM_MAX_COST_USD=0 可停用護欄（不建議用於生產環境）。
    """
    if MAX_COST_PER_CALL_USD <= 0:
        return  # 護欄已停用

    # 中文 + 英文混合：以每 3 char ≈ 1 token 估算（保守）
    estimated_input_tokens = (len(system_prompt) + len(user_prompt)) // 3
    estimated_cost = _estimate_cost(estimated_input_tokens, max_tokens)

    logger.debug(
        "cost_guard estimated_input_tokens=%d max_output_tokens=%d estimated_usd=%.5f limit_usd=%.2f",
        estimated_input_tokens,
        max_tokens,
        estimated_cost,
        MAX_COST_PER_CALL_USD,
    )

    if estimated_cost > MAX_COST_PER_CALL_USD:
        raise RuntimeError(
            f"COST_GUARD_EXCEEDED: estimated ${estimated_cost:.4f} > limit ${MAX_COST_PER_CALL_USD:.2f} "
            f"(input_tokens~{estimated_input_tokens}, max_output={max_tokens}). "
            f"Raise LLM_MAX_COST_USD or shorten prompt."
        )


# --- 真實實作（呼叫 OpenAI） ---


def _client():
    """惰性 import，避免 mock 模式下硬依賴 openai 套件。"""
    from openai import OpenAI

    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )


def _real_generate_script(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    response_format: dict | None,
) -> str:
    # 成本護欄：先估算，超限直接拒絕，不浪費 API 呼叫（rule-ai-llm）
    _check_cost_guard(system_prompt, user_prompt, max_tokens)

    last_err: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            kwargs: dict[str, Any] = {
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_completion_tokens": max_tokens,
            }
            if response_format:
                kwargs["response_format"] = response_format
            resp = _client().chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)
            logger.info(
                "llm.generate_script ok attempt=%d tokens=%s",
                attempt + 1,
                getattr(usage, "total_tokens", "?"),
            )
            return text
        except Exception as e:
            last_err = e
            logger.warning(
                "llm.generate_script retry attempt=%d err=%s",
                attempt + 1,
                type(e).__name__,
            )
            if attempt < MAX_RETRIES:
                time.sleep(1.0 * (2**attempt))  # exponential backoff: 1s, 2s
    raise RuntimeError(
        f"SCRIPT_GENERATION_FAILED: {type(last_err).__name__ if last_err else 'unknown'}"
    )


def _real_scan_compliance(text: str, platform: str) -> list[dict]:
    """真實實作待 Phase 4 service 整合測試後再決定要不要打這層 API。"""
    raise NotImplementedError(
        "real LLM compliance scan not implemented; "
        "use domain.compliance_rules.scan() for hardcoded keyword check"
    )


def _real_compute_dna(samples: list[dict]) -> dict:
    """真實實作待 sample 結構穩定後寫。"""
    raise NotImplementedError("real DNA computation not implemented yet")


# --- Mock 實作（無 key 時用，輸出符合 domain.prompts 規格） ---


def _mock_generate_script(user_prompt: str) -> str:
    """回傳 JSON 字串，欄位符合 domain.prompts 三樣板的輸出規格。"""
    if "Reels 60" in user_prompt or "ig_reels" in user_prompt:
        payload: dict[str, Any] = {
            "segments": [
                {"time": "0-10s", "scene": "[MOCK] hook 畫面", "voiceover": "[MOCK] 你以前是不是也...", "caption_overlay": "[MOCK] hook", "sfx": "[MOCK] 輕快"},
                {"time": "10-30s", "scene": "[MOCK] 痛點故事", "voiceover": "[MOCK] 痛點描述", "caption_overlay": "[MOCK] 共鳴", "sfx": "[MOCK] 情感"},
                {"time": "30-50s", "scene": "[MOCK] before/after", "voiceover": "[MOCK] 轉折+產品", "caption_overlay": "[MOCK] 對比", "sfx": "[MOCK] 亮起"},
                {"time": "50-60s", "scene": "[MOCK] CTA", "voiceover": "[MOCK] CTA 文字", "caption_overlay": "[MOCK] action", "sfx": "[MOCK] 結尾"},
            ],
            "caption": "[MOCK] caption hook + CTA",
            "hashtags": ["#mock", "#scriptflow"],
            "cta_variants": _mock_cta(),
        }
    elif "30 秒" in user_prompt or "threads_reel" in user_prompt:
        payload = {
            "segments": [
                {"time": "0-5s", "scene": "[MOCK] hook", "voiceover": "[MOCK]", "sfx": "[MOCK]"},
                {"time": "5-15s", "scene": "[MOCK] 痛點+解方", "voiceover": "[MOCK]", "sfx": "[MOCK]"},
                {"time": "15-25s", "scene": "[MOCK] 產品展示", "voiceover": "[MOCK]", "sfx": "[MOCK]"},
                {"time": "25-30s", "scene": "[MOCK] CTA", "voiceover": "[MOCK]", "sfx": "[MOCK]"},
            ],
            "cta_variants": _mock_cta(),
        }
    else:
        payload = {
            "content": "[MOCK] 短影音腳本貼文內容...",
            "cta_variants": _mock_cta(),
        }
    return json.dumps(payload, ensure_ascii=False)


def _mock_cta() -> list[dict]:
    return [
        {"type": "story_link", "text": "[MOCK] 限動連結搶最後 N 組"},
        {"type": "dm_keyword", "text": "[MOCK] 私訊關鍵字 GET"},
        {"type": "comment_engage", "text": "[MOCK] 留言 +1 我傳給你"},
    ]


def _mock_scan_compliance(text: str, platform: str) -> list[dict]:
    """Mock 不 flag 任何 LLM 層問題（domain.compliance_rules 已負責關鍵字層）。"""
    return []


def _mock_compute_dna(samples: list[dict]) -> dict:
    return {
        "best_opening": {
            "template": "[MOCK] 「以前我都 ___ 直到我換了 ___」",
            "avg_completion_rate": 0.71,
        },
        "best_cta": {
            "template": "[MOCK] 限動連結搶最後 N 組",
            "avg_ctr": 0.074,
        },
        "best_product_timing": {
            "position": "50%",
            "context": "before_after",
            "conversion_multiplier": 4.5,
        },
    }

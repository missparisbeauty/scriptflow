"""統一業務例外 — Phase 4。

設計（rule-backend）：
  - service 拋這些例外，不回 None / tuple
  - route 不寫 try/catch，由集中 error handler 統一轉成 spec 規定的 response 格式
  - 各例外帶 error_code，對應 spec-developer 的錯誤碼清單

對應 spec-developer：
  - CANDIDATES_NOT_READY     — 今日候選尚未產生
  - SCRIPT_GENERATION_FAILED — LLM 三次重試後仍失敗
  - IMAGE_GEN_FAILED         — 圖像生成失敗（StoryboardService 大多吞掉，少數抛）
  - INSUFFICIENT_DATA        — DNA 樣本 < 5
  - NOT_FOUND                — 資源不存在（4xx 通用）
"""

from __future__ import annotations


class ScriptFlowError(Exception):
    """所有業務例外的 base class。"""

    error_code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "", **details) -> None:
        super().__init__(message)
        self.message = message or self.error_code
        self.details: dict = details


class CandidatesNotReady(ScriptFlowError):
    error_code = "CANDIDATES_NOT_READY"
    http_status = 409


class ScriptGenerationFailed(ScriptFlowError):
    error_code = "SCRIPT_GENERATION_FAILED"
    http_status = 502


class ImageGenFailed(ScriptFlowError):
    error_code = "IMAGE_GEN_FAILED"
    http_status = 502


class InsufficientData(ScriptFlowError):
    error_code = "INSUFFICIENT_DATA"
    http_status = 409


class ResourceNotFound(ScriptFlowError):
    error_code = "NOT_FOUND"
    http_status = 404


class InvalidInput(ScriptFlowError):
    error_code = "INVALID_INPUT"
    http_status = 400

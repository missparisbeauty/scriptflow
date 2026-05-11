"""腳本生成 route — Phase 5 + latest recovery endpoint。

POST /api/v1/script/generate     生成三版本腳本（LLM 端點，慢）
GET  /api/v1/script/latest       拉最近一次生成的腳本（救援用，無 LLM 呼叫）
  錯誤碼：SCRIPT_GENERATION_FAILED（502）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from domain.responses import ok
from modules.auth.middleware import require_session
from modules.script.schema import GenerateRequest
from modules.script.service import generate, get_latest_script

router = APIRouter(
    prefix="/api/v1/script",
    tags=["script"],
    dependencies=[Depends(require_session)],
)


@router.post("/generate")
def generate_script(req: GenerateRequest) -> dict:
    data = generate(
        req.candidate_ids,
        req.category,
        script_type=req.script_type,
        selected_item_index=req.selected_item_index,
    )
    return ok(data)


@router.get("/latest")
def latest_script() -> dict:
    """拉最近一次生成的腳本。無腳本回 404。"""
    script = get_latest_script()
    if not script:
        raise HTTPException(status_code=404, detail="no script generated yet")
    return ok(script)

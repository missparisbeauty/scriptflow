"""腳本生成 route — Phase 5。

POST /api/v1/script/generate
  錯誤碼：SCRIPT_GENERATION_FAILED（502）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from domain.responses import ok
from modules.auth.middleware import require_session
from modules.script.schema import GenerateRequest
from modules.script.service import generate

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

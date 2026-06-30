"""AI 相談 API。全データ文脈 + 会話履歴(クライアント保持)で回答する。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.llm.consult import consult

router = APIRouter()


class ConsultMsg(BaseModel):
    role: str
    content: str


class ConsultIn(BaseModel):
    messages: list[ConsultMsg] = Field(default_factory=list)


@router.post("/api/consult")
async def post_consult(body: ConsultIn) -> dict[str, Any]:
    reply = await consult([m.model_dump() for m in body.messages])
    if reply is None:
        raise HTTPException(status_code=502, detail="相談の生成に失敗(LLM 未設定または応答なし)")
    return {"reply": reply}

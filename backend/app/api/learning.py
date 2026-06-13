"""The Rust Book 完走プランの進捗 API。

カリキュラム・状態計算は app.scoring.learning に委譲し、ここは HTTP 層のみ。
journey リポジトリの git hook からは POST /api/learning/activity を叩く。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.scoring import learning

router = APIRouter()


@router.get("/api/learning/state")
async def learning_state() -> dict[str, Any]:
    return learning.state()


class SectionCheckIn(BaseModel):
    field: Literal["read", "explained"]
    done: bool = True
    done_at_iso: str | None = None  # 過去の学習を記録する場合 (例 6/13 14:30)


@router.post("/api/learning/section/{section_id}/check")
async def check_section(section_id: str, body: SectionCheckIn) -> dict[str, Any]:
    try:
        return learning.set_section_check(
            section_id, body.field, body.done, done_at_iso=body.done_at_iso
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class RustlingsIn(BaseModel):
    done: bool = True
    done_at_iso: str | None = None


@router.post("/api/learning/chapter/{chapter}/rustlings")
async def check_rustlings(chapter: int, body: RustlingsIn) -> dict[str, Any]:
    """章単位の Rustlings 達成をトグル (演習のある章のみ)。"""
    try:
        return learning.set_chapter_rustlings(chapter, body.done, done_at_iso=body.done_at_iso)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class QuizMsg(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class QuizIn(BaseModel):
    messages: list[QuizMsg] = []


@router.post("/api/learning/chapter/{chapter}/quiz")
async def chapter_quiz(chapter: int, body: QuizIn) -> dict[str, Any]:
    """章の口頭試問を 1 ターン進める。合格判定が出たら章の全節 explained を立てる。"""
    from app.llm import quiz as quiz_mod

    try:
        result = await quiz_mod.quiz_turn(chapter, [m.model_dump() for m in body.messages])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:  # LLM 接続失敗は会話として穏便に返す
        return {
            "reply": "(試験官に接続できませんでした。少し待ってから再試行してください)",
            "verdict": {"decided": False, "passed": None, "feedback": None},
            "error": True,
        }
    if result["verdict"]["decided"] and result["verdict"]["passed"]:
        result["state"] = learning.mark_chapter_explained(chapter)
    return result


class ActivityIn(BaseModel):
    detail: str | None = None


@router.post("/api/learning/activity")
async def record_activity(body: ActivityIn) -> dict[str, Any]:
    return learning.record_activity(body.detail)


class PlanIn(BaseModel):
    started_on: str | None = None  # YYYY-MM-DD
    target_date: str | None = None
    clear_started: bool = False
    clear_target: bool = False


@router.post("/api/learning/plan")
async def set_plan(body: PlanIn) -> dict[str, Any]:
    try:
        return learning.set_plan(
            started_on=body.started_on, target_date=body.target_date,
            clear_started=body.clear_started, clear_target=body.clear_target,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

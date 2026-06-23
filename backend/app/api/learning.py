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
    # exam=口頭試問 (採点あり) / review=クリア後の復習チューター (採点なし)
    mode: Literal["exam", "review"] = "exam"
    # 回答形式。free=フリーワード(LLM採点) / choice4=4択 / choice2=2択
    format: Literal["free", "choice4", "choice2"] = "free"
    # 選択式の 2 段階フロー。question=問題生成 / answer=採点 (free は常に answer 相当)
    action: Literal["question", "answer"] = "answer"
    selected_index: int | None = None  # 選択式: ユーザーが選んだ index
    correct_index: int | None = None  # 選択式: 出題時に返した正解 index (client がエコー)


async def _free_word_turn(chapter: int, msgs: list[dict[str, Any]]) -> dict[str, Any]:
    """フリーワード 1 ターン: LLM 採点 → 得点付与 → クリア判定。"""
    from app.llm import quiz as quiz_mod

    result = await quiz_mod.quiz_turn(chapter, msgs)
    result["format"] = "free"
    # ユーザーが実際に回答したターンだけ加点する (冒頭の質問だけのターンは加点しない)。
    answered = bool(msgs) and msgs[-1].get("role") == "user"
    if answered:
        award = learning.award_quiz_points(chapter, free_understanding=result["understanding"])
        result.update(
            quiz_points=award["quiz_points"], target=award["target"],
            free_word_passed=award["free_word_passed"], gained=award["gained"],
            cleared=award["cleared"],
        )
        if award["cleared"]:
            result["state"] = award["state"]
    else:
        prog = learning.chapter_quiz_progress(chapter)
        result.update(
            quiz_points=prog["quiz_points"], target=prog["target"],
            free_word_passed=prog["free_word_passed"], gained=0, cleared=False,
        )
    return result


@router.post("/api/learning/chapter/{chapter}/quiz")
async def chapter_quiz(chapter: int, body: QuizIn) -> dict[str, Any]:
    """章の理解度チェック / 復習チャットを 1 ターン進める。

    - mode=review: クリア後の自由な復習対話 (採点しない)。
    - format=free: フリーワード採点 → 得点付与。
    - format=choice4/choice2 + action=question: 選択式の問題を生成。
    - format=choice4/choice2 + action=answer: 選択式の採点 (得点付与)。
    累計得点が閾値に達し、かつフリーワード正解が 1 回以上あれば章クリア。
    """
    from app.llm import quiz as quiz_mod

    msgs = [m.model_dump() for m in body.messages]
    is_review = body.mode == "review"
    try:
        if is_review:
            return await quiz_mod.tutor_turn(chapter, msgs)
        if body.format == "free":
            return await _free_word_turn(chapter, msgs)
        # --- 選択式 ---
        n = 4 if body.format == "choice4" else 2
        if body.action == "question":
            q = await quiz_mod.choice_question(chapter, msgs, n)
            prog = learning.chapter_quiz_progress(chapter)
            return {**q, "format": body.format, **prog}
        # action == "answer": client 採点した正誤を受けて加点
        correct = body.selected_index is not None and body.selected_index == body.correct_index
        award = learning.award_quiz_points(chapter, choice_correct=correct, fmt=body.format)
        return {"correct": correct, "format": body.format, **award}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:  # LLM 接続失敗は会話として穏便に返す
        if is_review:
            return {"reply": "(チューターに接続できませんでした。少し待ってから再試行してください)",
                    "review": True, "error": True}
        return {
            "reply": "(試験官に接続できませんでした。少し待ってから再試行してください)",
            "understanding": 0, "threshold": 80, "cleared": False, "error": True,
        }


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

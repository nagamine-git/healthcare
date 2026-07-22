"""種目デモ GIF 配信 (ExerciseDB プロキシ＆キャッシュ) + 候補ピッカー・手動確定。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.models import ExerciseGuide

router = APIRouter()


def _resolve_with_override(name: str) -> tuple[str | None, str]:
    """DB の手動確定 (override) → curated → 自動候補 の優先順で ID を解決する。"""
    from app.db import session_scope
    from app.integrations.exercisedb import curated_id, exercise_key, resolve_id
    from app.models import ExerciseGifOverride

    key = exercise_key(name)
    with session_scope() as session:
        override = session.get(ExerciseGifOverride, key)
        if override is not None:
            return override.exercisedb_id, "override"
    cid = curated_id(name)
    if cid is not None:
        return cid, "curated"
    return resolve_id(name), "auto"


@router.get("/api/exercise-gif")
async def exercise_gif(name: str, id: str | None = None) -> Response:
    """種目名 (JA) のデモ GIF。id 指定時は候補ピッカーのプレビュー用にそれを直接使う。

    マップ外/未取得は 404 (フロントは img を隠す)。
    """
    from app.integrations.exercisedb import fetch_gif_by_id

    def _resolve() -> str | None:
        if id:
            return id
        exercise_id, _source = _resolve_with_override(name)
        return exercise_id

    exercise_id = await run_in_threadpool(_resolve)
    if exercise_id is None:
        return Response(status_code=404)
    gif = await run_in_threadpool(fetch_gif_by_id, exercise_id)
    if gif is None:
        return Response(status_code=404)
    return Response(
        content=gif,
        media_type="image/gif",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/api/exercise-candidates")
async def exercise_candidates(name: str) -> dict[str, Any]:
    """現在の選択 (override/curated/auto) + 器具限定の候補一覧。候補ピッカー UI 用。"""
    from app.integrations.exercisedb import fetch_detail_by_id, is_configured, list_candidates

    def _work() -> dict[str, Any]:
        selected_id, source = _resolve_with_override(name)
        candidates = list_candidates(name, limit=6)
        selected: dict[str, Any] | None = None
        if selected_id is not None:
            match = next((c for c in candidates if c["id"] == selected_id), None)
            if match is None:
                detail = fetch_detail_by_id(selected_id)
                match = detail if detail else {"id": selected_id, "name": None,
                                                "equipment": None, "target": None}
            selected = {**match, "source": source}
        for c in candidates:
            c["selected"] = selected_id is not None and c["id"] == selected_id
        # configured=False なら「候補なし」ではなく「連携が未設定」。UI が言い分ける。
        return {"selected": selected, "candidates": candidates, "configured": is_configured()}

    return await run_in_threadpool(_work)


class ExerciseOverrideIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    exercisedb_id: str = Field(min_length=1, max_length=16)
    exercisedb_name: str = Field(min_length=1, max_length=200)


@router.post("/api/exercise-override")
async def save_exercise_override(body: ExerciseOverrideIn) -> dict[str, Any]:
    """候補ピッカーでの選択を確定・永続化 (以後この種目は常にこの GIF を使う)。"""
    from app.db import session_scope
    from app.integrations.exercisedb import exercise_key
    from app.models import ExerciseGifOverride

    def _work() -> dict[str, Any]:
        key = exercise_key(body.name)
        with session_scope() as session:
            row = session.get(ExerciseGifOverride, key)
            if row is None:
                row = ExerciseGifOverride(exercise_key=key)
                session.add(row)
            row.exercisedb_id = body.exercisedb_id
            row.exercisedb_name = body.exercisedb_name
            row.updated_at = datetime.utcnow()
        return {"ok": True}

    return await run_in_threadpool(_work)


@router.delete("/api/exercise-override")
async def delete_exercise_override(name: str) -> dict[str, Any]:
    """手動確定を解除し、curated/自動候補に戻す。"""
    from app.db import session_scope
    from app.integrations.exercisedb import exercise_key
    from app.models import ExerciseGifOverride

    def _work() -> dict[str, Any]:
        key = exercise_key(name)
        with session_scope() as session:
            row = session.get(ExerciseGifOverride, key)
            if row is not None:
                session.delete(row)
        return {"ok": True}

    return await run_in_threadpool(_work)


def _guide_to_dict(row: ExerciseGuide) -> dict[str, Any]:
    return {
        "cached": True,
        "exercise_key": row.exercise_key,
        "name_ja": row.name_ja,
        "steps": row.steps_json,
        "model": row.model,
        "created_at": (
            row.created_at.replace(tzinfo=UTC).isoformat() if row.created_at else None
        ),
    }


class ExerciseGuideIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.get("/api/exercise-guide")
async def exercise_guide(name: str) -> Response:
    """種目名 (JA) の保存済みステップ式フォームガイド。

    未生成 (キャッシュなし) は 204 (LLM は勝手に呼ばない。生成は POST で行う)。
    """
    from app.db import session_scope
    from app.integrations.exercisedb import exercise_key
    from app.models import ExerciseGuide

    def _work() -> dict[str, Any] | None:
        key = exercise_key(name)
        with session_scope() as session:
            row = session.get(ExerciseGuide, key)
            return _guide_to_dict(row) if row is not None else None

    data = await run_in_threadpool(_work)
    if data is None:
        return Response(status_code=204)
    return JSONResponse(data)


@router.post("/api/exercise-guide")
async def create_exercise_guide(body: ExerciseGuideIn, force: bool = False) -> dict[str, Any]:
    """ステップ式フォームガイドを LLM で生成して保存。保存済みならそれを返す (冪等・LLM はタップ時の1回だけ)。"""
    from app.db import session_scope
    from app.integrations.exercisedb import exercise_key
    from app.models import ExerciseGuide

    key = exercise_key(body.name)
    with session_scope() as session:
        existing = session.get(ExerciseGuide, key)
        if existing is not None and not force:
            return _guide_to_dict(existing)

    from app.llm.exercise_guide import generate_guide

    got = await generate_guide(body.name)
    if got is None:
        raise HTTPException(status_code=503, detail="ガイドを生成できませんでした (LLM 未設定/失敗)")
    with session_scope() as session:
        row = session.get(ExerciseGuide, key)
        if row is None:
            row = ExerciseGuide(exercise_key=key, name_ja=got["name_ja"], steps_json=got["steps"])
            session.add(row)
        row.name_ja = got["name_ja"]
        row.steps_json = got["steps"]
        row.model = got.get("model")
        row.created_at = datetime.utcnow()
        session.flush()
        return _guide_to_dict(row)

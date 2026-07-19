"""種目デモ GIF 配信 (ExerciseDB プロキシ＆キャッシュ)。"""

from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.concurrency import run_in_threadpool

router = APIRouter()


@router.get("/api/exercise-gif")
async def exercise_gif(name: str) -> Response:
    """種目名 (JA) のデモ GIF。マップ外/未取得は 404 (フロントは img を隠す)。"""
    from app.integrations.exercisedb import get_gif

    gif = await run_in_threadpool(get_gif, name)
    if gif is None:
        return Response(status_code=404)
    return Response(
        content=gif,
        media_type="image/gif",
        headers={"Cache-Control": "public, max-age=604800"},
    )

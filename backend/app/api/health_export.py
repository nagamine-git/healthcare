from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.db import session_scope
from app.ingest.hae_parser import parse_payload
from app.ingest.hae_writer import write_parse_result

router = APIRouter()


def _verify_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.hae_ingest_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="HAE_INGEST_TOKEN is not configured.",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required.")
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")


def _recompute_today_after_ingest() -> None:
    """取り込んだ新データを即スコアに反映 (レスポンス後にバックグラウンド実行)。"""
    from app.scoring.recompute import ensure_today_fresh

    # ⚠️ かつてここは `min_interval_s=0` でスロットルを**無効化**していた。
    # Health Auto Export は HealthKit の変化のたびに送ってくるため、取り込み1回ごとに
    # その日のスコアを**丸ごと再計算**することになり、本番では取り込みが 2790 回・
    # 最大 89.6 秒という遅延記録が残っていた (アプリ自身の /api/admin/perf より)。
    # その再計算が CPU と DB 書き込みを占有し、`/api/today` の最大 139 秒に繋がっていた。
    #
    # 既定のスロットル (120秒) を使う。スコアは「その日の総合点」であって秒単位の
    # 鮮度は要らないので、最悪 2 分遅れて反映されても実用上まったく問題にならない。
    ensure_today_fresh()


@router.post("/ingest/health-auto-export", status_code=status.HTTP_202_ACCEPTED)
def ingest_health_auto_export(
    payload: dict[str, Any], background: BackgroundTasks, _: None = Depends(_verify_token)
) -> dict[str, Any]:
    parsed = parse_payload(payload)
    with session_scope() as session:
        counts = write_parse_result(session, parsed)
    # 新データ到着 → 今日の総合点を再計算 (HealthKit は変化時同期なので near-real-time)
    background.add_task(_recompute_today_after_ingest)
    return {"status": "ok", "counts": counts}

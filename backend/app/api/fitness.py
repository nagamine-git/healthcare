"""自宅フィットネスチェック API。

テスト定義・基準値はコード (scoring/fitness_test.py) に持ち、ここは結果の
記録 (UPSERT) と概要の取得を担う。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import FitnessTestResult
from app.scoring.fitness_test import (
    FITNESS_TESTS,
    build_overview,
    grip_best,
)

router = APIRouter()


def _today_jst():
    settings = get_settings()
    return datetime.now(ZoneInfo(settings.app_tz)).date()


class FitnessResultIn(BaseModel):
    test_key: str
    value: float | None = Field(default=None)
    # 握力など左右別入力 (両方指定時は value をベストで上書き)
    left: float | None = Field(default=None, gt=0)
    right: float | None = Field(default=None, gt=0)
    performed_on: str | None = None  # "YYYY-MM-DD"、無ければ JST 今日
    note: str | None = None


@router.get("/api/fitness/tests")
async def get_fitness_tests() -> dict[str, Any]:
    """全テストの定義 + 最新結果 + 評価 + トレンド + 次回推奨。"""
    return build_overview(_today_jst())


@router.post("/api/fitness/results")
async def record_fitness_result(body: FitnessResultIn) -> dict[str, Any]:
    defn = FITNESS_TESTS.get(body.test_key)
    if defn is None:
        raise HTTPException(status_code=400, detail=f"unknown test_key: {body.test_key}")

    detail: dict[str, Any] | None = None
    if body.left is not None or body.right is not None:
        value = grip_best(body.left, body.right)
        detail = {"left": body.left, "right": body.right}
    else:
        value = body.value
    if value is None:
        raise HTTPException(status_code=400, detail="value (または left/right) が必要です")

    if body.performed_on:
        try:
            performed_on = datetime.strptime(body.performed_on, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid performed_on: {exc}") from exc
    else:
        performed_on = _today_jst()

    with session_scope() as session:
        existing = session.execute(
            select(FitnessTestResult).where(
                FitnessTestResult.test_key == body.test_key,
                FitnessTestResult.performed_on == performed_on,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.value = value
            existing.detail_json = detail
            existing.note = body.note
            row = existing
        else:
            row = FitnessTestResult(
                test_key=body.test_key,
                performed_on=performed_on,
                value=value,
                detail_json=detail,
                note=body.note,
            )
            session.add(row)
        session.flush()
        return {
            "id": row.id,
            "test_key": row.test_key,
            "performed_on": row.performed_on.isoformat(),
            "value": row.value,
            "detail": row.detail_json,
        }


@router.get("/api/fitness/history/{test_key}")
async def get_fitness_history(test_key: str, limit: int = 24) -> dict[str, Any]:
    if test_key not in FITNESS_TESTS:
        raise HTTPException(status_code=400, detail=f"unknown test_key: {test_key}")
    with session_scope() as session:
        rows = (
            session.execute(
                select(FitnessTestResult)
                .where(FitnessTestResult.test_key == test_key)
                .order_by(FitnessTestResult.performed_on.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        items = [
            {
                "id": r.id,
                "performed_on": r.performed_on.isoformat(),
                "value": r.value,
                "detail": r.detail_json,
                "note": r.note,
            }
            for r in rows
        ]
    return {"test_key": test_key, "items": items}


@router.delete("/api/fitness/results/{result_id}")
async def delete_fitness_result(result_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(FitnessTestResult, result_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        return {"deleted": result_id}

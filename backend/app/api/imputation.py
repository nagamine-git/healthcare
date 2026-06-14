"""欠損した一次健康指標の統計的補完 API (読み取り専用)。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from app.scoring import forecast as forecast_mod
from app.scoring import imputation
from app.scoring import predict as predict_mod
from app.scoring.timewindow import app_today

router = APIRouter()


@router.get("/api/imputation")
async def get_imputation(date: str | None = None) -> dict[str, Any]:
    target = date_from(date)
    return {
        "date": target.isoformat(),
        "imputed": imputation.impute_day(target, only_missing=True),
    }


@router.get("/api/forecast")
async def get_forecast() -> dict[str, Any]:
    """未来予測 (片頭痛リスク / エネルギー推移 / 明日の指標)。"""
    return forecast_mod.forecast()


@router.get("/api/predict/{metric}")
async def get_predict(
    metric: str, days_back: int = 14, days_ahead: int = 7,
    date_from: str | None = None, date_to: str | None = None,
) -> dict[str, Any]:
    """統一予測: 任意指標を [from, to] で 実測/推定(過去欠損)/予報(未来) で埋めて返す。"""
    today = app_today()
    start = date.fromisoformat(date_from) if date_from else today - timedelta(days=max(0, days_back))
    end = date.fromisoformat(date_to) if date_to else today + timedelta(days=max(0, days_ahead))
    if (end - start).days > 120:
        raise HTTPException(status_code=400, detail="range too large (max 120 days)")
    try:
        return predict_mod.predict_series(metric, start, end, today=today)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def date_from(s: str | None) -> date:
    from datetime import date as _date
    return _date.fromisoformat(s) if s else app_today()

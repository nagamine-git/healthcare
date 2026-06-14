"""欠損した一次健康指標の統計的補完 API (読み取り専用)。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter

from app.scoring import forecast as forecast_mod
from app.scoring import imputation
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


def date_from(s: str | None) -> date:
    from datetime import date as _date
    return _date.fromisoformat(s) if s else app_today()

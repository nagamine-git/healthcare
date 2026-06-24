"""天気予報・降水確率 API。

スコアリング/整形は app.integrations.weather_forecast に委譲し、ここは HTTP 層のみ。
地点は config の WEATHER_LATITUDE/LONGITUDE 固定 (読み取り専用)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.integrations.weather_forecast import get_weather_forecast

router = APIRouter()


@router.get("/api/weather")
async def get_weather() -> dict[str, Any]:
    """今日の天気サマリ + 時間別(今日明日)+ 週間(7日)を返す。取得失敗時は available=False。"""
    data = get_weather_forecast()
    if data is None:
        return {"available": False, "summary": None, "hourly": [], "daily": []}
    return {"available": True, **data}

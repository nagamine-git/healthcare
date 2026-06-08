"""海面気圧の履歴を MetricSample に保存する (頭痛トリガー分析用)。

ライブのスナップショット (integrations/weather.py) は過去 48h しか持たないため、
過去の頭痛と気圧を事後照合できるよう、Open-Meteo Archive API で履歴を
バックフィルして永続化する。

時刻は UTC naive で保存する (MigraineEpisode.started_at と同じ規約)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.logging import get_logger
from app.models import MetricSample

logger = get_logger(__name__)

METRIC_KEY = "surface_pressure_hpa"
_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def store_pressure_samples(
    session: Session, times: list[str], values: list[float | None]
) -> int:
    """ISO 時刻 (UTC, 例 '2026-06-01T00:00') と hPa 値の列を upsert。書いた件数を返す。"""
    payload: list[dict[str, Any]] = []
    for t, v in zip(times, values, strict=True):
        if v is None:
            continue
        ts = datetime.fromisoformat(t).replace(tzinfo=None)
        payload.append({
            "source": "open-meteo",
            "metric_key": METRIC_KEY,
            "ts": ts,
            "value": float(v),
            "unit": "hPa",
        })
    if not payload:
        return 0
    stmt = sqlite_insert(MetricSample).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[MetricSample.source, MetricSample.metric_key, MetricSample.ts],
        set_={"value": stmt.excluded.value},
    )
    session.execute(stmt)
    return len(payload)


def _fetch_archive(lat: float, lon: float, start_date: str, end_date: str) -> dict[str, Any] | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pressure_msl",
        "timezone": "GMT",  # UTC で受け取り、UTC naive 保存する
        "start_date": start_date,
        "end_date": end_date,
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(_ARCHIVE_URL, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("open_meteo_archive_failed", error=str(exc))
        return None


def backfill_pressure_history(days: int = 120) -> int:
    """過去 days 日分の気圧を Archive API から取得して保存。書いた件数を返す。

    Archive API は数日の反映遅れがあるため、終端は 2 日前にする。
    """
    s = get_settings()
    end = (datetime.now(UTC) - timedelta(days=2)).date()
    start = end - timedelta(days=days)
    raw = _fetch_archive(s.weather_latitude, s.weather_longitude, start.isoformat(), end.isoformat())
    if not raw or "hourly" not in raw:
        return 0
    hourly = raw["hourly"]
    times = hourly.get("time") or []
    values = hourly.get("pressure_msl") or []
    if not times:
        return 0
    with session_scope() as session:
        return store_pressure_samples(session, times, values)

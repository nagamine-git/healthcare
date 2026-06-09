from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db import session_scope
from app.models import MetricSample


def test_store_pressure_samples_upserts(db_engine):
    from app.ingest.pressure_history import store_pressure_samples

    times = ["2026-06-01T00:00", "2026-06-01T01:00", "2026-06-01T02:00"]
    values = [1013.0, 1012.5, None]  # None はスキップ

    with session_scope() as s:
        n = store_pressure_samples(s, times, values)
    assert n == 2

    with session_scope() as s:
        rows = s.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.metric_key == "surface_pressure_hpa").order_by(MetricSample.ts)
        ).all()
    assert len(rows) == 2
    assert rows[0] == (datetime(2026, 6, 1, 0, 0), 1013.0)

    # 再投入は upsert (重複しない、値は更新)
    with session_scope() as s:
        store_pressure_samples(s, ["2026-06-01T00:00"], [1009.0])
    with session_scope() as s:
        rows = s.execute(
            select(MetricSample.value).where(
                MetricSample.metric_key == "surface_pressure_hpa",
                MetricSample.ts == datetime(2026, 6, 1, 0, 0))
        ).all()
    assert len(rows) == 1 and rows[0][0] == 1009.0


def test_backfill_pressure_history_uses_archive(db_engine, monkeypatch):
    from app.ingest import pressure_history

    captured: dict = {}

    def fake_fetch(lat, lon, start_date, end_date):
        captured["args"] = (lat, lon, start_date, end_date)
        return {
            "hourly": {
                "time": ["2026-05-01T00:00", "2026-05-01T01:00"],
                "pressure_msl": [1015.0, 1014.0],
            }
        }

    monkeypatch.setattr(pressure_history, "_fetch_archive", fake_fetch)
    n = pressure_history.backfill_pressure_history(days=10)
    assert n == 2
    with session_scope() as s:
        cnt = s.execute(
            select(MetricSample.value).where(MetricSample.metric_key == "surface_pressure_hpa")
        ).all()
    assert len(cnt) == 2


def test_store_pressure_points_converts_jst_to_utc_and_skips_future(db_engine):
    from datetime import UTC, datetime, timedelta

    from app.ingest.pressure_history import store_pressure_points

    now = datetime.now(UTC)
    past_jst = (now - timedelta(hours=3)).astimezone().isoformat()
    future_jst = (now + timedelta(hours=3)).astimezone().isoformat()
    n = store_pressure_points([
        {"time_jst": past_jst, "pressure_hpa": 1011.0},
        {"time_jst": future_jst, "pressure_hpa": 1009.0},  # 未来はスキップ
    ])
    assert n == 1
    with session_scope() as s:
        rows = s.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.metric_key == "surface_pressure_hpa")
        ).all()
    assert len(rows) == 1
    # JST→UTC naive で保存され、過去点のみ
    assert rows[0][1] == 1011.0
    assert rows[0][0].tzinfo is None


def test_store_pressure_points_accepts_to_dict_format(db_engine):
    """weather.to_dict の series 形式 ({time, hpa}) を受け付ける。"""
    from datetime import UTC, datetime, timedelta

    from app.ingest.pressure_history import store_pressure_points

    past = (datetime.now(UTC) - timedelta(hours=2)).astimezone().isoformat()
    n = store_pressure_points([{"time": past, "hpa": 1007.5}])
    assert n == 1
    with session_scope() as s:
        rows = s.execute(
            select(MetricSample.value).where(MetricSample.metric_key == "surface_pressure_hpa")
        ).all()
    assert rows[0][0] == 1007.5

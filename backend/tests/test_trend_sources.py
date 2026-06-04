from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db import session_scope
from app.models import BodyBatteryDaily, HrvDaily, SleepSession, WeightSample


def test_raw_series_collects_per_metric(db_engine):
    from app.scoring import trend_sources as ts

    today = date(2026, 5, 20)
    with session_scope() as session:
        for i in range(5):
            d = today - timedelta(days=i)
            session.add(SleepSession(date=d, source="garmin", total_min=420 + i * 10, sleep_score=80))
            session.add(HrvDaily(date=d, last_night_avg=60 + i, weekly_avg=60, status="BALANCED"))
            session.add(BodyBatteryDaily(date=d, max_value=90, min_value=20, end_of_day=40, morning_value=70 + i))
            session.add(WeightSample(ts=datetime.combine(d, datetime.min.time()),
                                     weight_kg=70.0 + i * 0.1, body_fat_pct=18.0, source="hae"))

    bundle = ts.collect_raw_series(today, days=28)
    assert len(bundle["sleep"]) == 5
    assert len(bundle["hrv"]) == 5
    assert len(bundle["energy"]) == 5
    assert len(bundle["weight"]) == 5
    assert len(bundle["body_fat"]) == 5
    assert bundle["sleep"][0][1] in (420, 430, 440, 450, 460)
    assert bundle["hrv_baseline"] is not None

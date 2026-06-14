from __future__ import annotations

from datetime import date, timedelta

from app.db import session_scope
from app.models import HrvDaily
from app.scoring import predict


def test_series_mixes_actual_imputed_forecast(db_engine):
    today = date(2026, 6, 14)
    with session_scope() as s:
        # 過去60日のうち偶数日だけ実測 (奇数日は欠損 → 推定対象)
        for i in range(1, 61):
            d = today - timedelta(days=i)
            if i % 2 == 0:
                s.add(HrvDaily(date=d, last_night_avg=55.0 + (i % 7), weekly_avg=55.0))
    out = predict.predict_series("hrv", today - timedelta(days=10), today + timedelta(days=5), today=today)
    kinds = {p["date"]: p["kind"] for p in out["points"]}
    assert out["metric"] == "hrv" and out["unit"] == "ms"
    # 実測がある過去偶数日は actual
    assert kinds[(today - timedelta(days=10)).isoformat()] == "actual"
    # 実測が無い過去奇数日は imputed (区間つき)
    imp_pt = next(p for p in out["points"] if p["kind"] == "imputed")
    assert imp_pt["low"] is not None and imp_pt["high"] is not None
    assert imp_pt["confidence"] in ("high", "medium", "low")
    # 未来日は forecast
    fut = [p for p in out["points"] if p["kind"] == "forecast"]
    assert len(fut) == 5
    assert all(p["confidence"] in ("medium", "low") for p in fut)  # 未来は確度を下げる


def test_unknown_metric_raises(db_engine):
    import pytest
    with pytest.raises(ValueError):
        predict.predict_series("bogus", date(2026, 6, 1), date(2026, 6, 14))


def test_today_present_is_actual(db_engine):
    today = date(2026, 6, 14)
    with session_scope() as s:
        s.add(HrvDaily(date=today, last_night_avg=60.0, weekly_avg=58.0))
    out = predict.predict_series("hrv", today, today, today=today)
    assert out["points"][0]["kind"] == "actual"
    assert out["points"][0]["value"] == 60.0

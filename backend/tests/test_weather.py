from __future__ import annotations

from datetime import datetime, timedelta

from app.integrations.weather import _classify_risk, _closest_index


def test_classify_risk_calm():
    level, _ = _classify_risk(
        6.0, 10.0, delta_24h=-2.0, delta_6h=-1.0, forecast_delta=-3.0
    )
    assert level == "calm"


def test_classify_risk_watch_for_future_drop():
    level, _ = _classify_risk(
        6.0, 10.0, delta_24h=0.0, delta_6h=0.0, forecast_delta=-7.0
    )
    assert level == "watch"


def test_classify_risk_warning_for_recent_drop():
    level, _ = _classify_risk(
        6.0, 10.0, delta_24h=-7.0, delta_6h=-3.0, forecast_delta=0.0
    )
    assert level == "warning"


def test_classify_risk_severe_for_24h_severe_drop():
    level, _ = _classify_risk(
        6.0, 10.0, delta_24h=-12.0, delta_6h=-3.0, forecast_delta=0.0
    )
    assert level == "severe"


def test_classify_risk_severe_for_6h_rapid_drop():
    level, _ = _classify_risk(
        6.0, 10.0, delta_24h=-2.0, delta_6h=-8.0, forecast_delta=0.0
    )
    assert level == "severe"


def test_classify_risk_handles_none_deltas():
    level, reason = _classify_risk(
        6.0, 10.0, delta_24h=None, delta_6h=None, forecast_delta=None
    )
    assert level == "calm"
    assert reason


def test_closest_index_finds_nearest_point():
    base = datetime(2026, 5, 23, 10, 0)
    times = [base + timedelta(hours=h) for h in range(0, 5)]
    target = base + timedelta(hours=2, minutes=20)
    # 2 時間後が最も近い
    assert _closest_index(times, target) == 2


def test_closest_index_empty():
    assert _closest_index([], datetime.now()) == -1

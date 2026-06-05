from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.scoring.morning_light import _steps_to_score, compute_morning_light_score


def test_steps_to_score_thresholds():
    assert _steps_to_score(0) == 0
    assert _steps_to_score(500) == pytest.approx(30.0, abs=0.1)
    assert _steps_to_score(3000) == pytest.approx(80.0, abs=0.1)
    assert _steps_to_score(6000) == pytest.approx(100.0, abs=0.1)
    assert _steps_to_score(10000) == 100.0  # ceiling


def test_steps_to_score_monotonic():
    prev = -1.0
    for s in range(0, 7000, 250):
        cur = _steps_to_score(s)
        assert cur >= prev
        prev = cur


@pytest.fixture
def session(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    from app.config import reset_settings_cache

    reset_settings_cache()
    from app.db import create_all, init_engine, session_scope

    init_engine(temp_data_dir / "test.sqlite3")
    create_all()
    with session_scope() as s:
        yield s


def test_morning_light_score_with_steps(session):
    from app.models import MetricSample

    target = date(2026, 5, 23)
    # 起床 06:30 JST → 06:30-09:30 JST のウィンドウ
    # UTC 換算: 21:30 (前日) - 00:30 (当日)
    jst = ZoneInfo("Asia/Tokyo")
    wake = datetime.combine(target, datetime.min.time(), jst).replace(hour=6, minute=30)
    for i in range(3):
        ts_jst = wake + timedelta(minutes=30 * i)
        session.add(
            MetricSample(
                source="garmin",
                metric_key="steps",
                ts=ts_jst.astimezone(UTC).replace(tzinfo=None),
                value=1000.0,  # 3 サンプル × 1000 = 3000 歩
            )
        )
    session.flush()

    out = compute_morning_light_score(session, target)
    assert out["steps_in_window"] == 3000
    assert out["score"] == pytest.approx(80.0, abs=0.5)


def test_morning_light_returns_none_with_no_data(session):
    out = compute_morning_light_score(session, date(2026, 5, 23))
    assert out["score"] is None
    assert "なし" in out["rationale"]


def test_daylight_min_to_score_curve():
    from app.scoring.morning_light import _daylight_min_to_score

    assert _daylight_min_to_score(0) == 0.0
    assert _daylight_min_to_score(5) == pytest.approx(30.0, abs=0.5)
    assert _daylight_min_to_score(15) == pytest.approx(70.0, abs=0.5)
    assert _daylight_min_to_score(30) == pytest.approx(95.0, abs=0.5)
    assert _daylight_min_to_score(60) == pytest.approx(100.0, abs=0.5)
    assert _daylight_min_to_score(120) == 100.0


def test_apple_daylight_takes_priority_over_steps(session):
    """Apple Health の time_in_daylight があれば歩数 proxy より優先される。"""
    from app.models import MetricSample

    target = date(2026, 5, 23)
    jst = ZoneInfo("Asia/Tokyo")
    wake = datetime.combine(target, datetime.min.time(), jst).replace(hour=6, minute=30)

    # 歩数は少なめ (proxy なら低スコア)
    session.add(
        MetricSample(
            source="garmin",
            metric_key="steps",
            ts=(wake + timedelta(minutes=15)).astimezone(UTC).replace(tzinfo=None),
            value=200.0,
        )
    )
    # 日光下 20 分 (proxy なら高スコア)
    session.add(
        MetricSample(
            source="hae",
            metric_key="time_in_daylight",
            ts=(wake + timedelta(minutes=30)).astimezone(UTC).replace(tzinfo=None),
            value=20.0,
            unit="min",
        )
    )
    session.flush()

    out = compute_morning_light_score(session, target)
    assert out["source"] == "apple_daylight"
    assert out["daylight_min"] == 20
    assert out["score"] is not None
    assert out["score"] >= 75  # 20 分 ≈ 78


def test_daylight_in_seconds_unit_converted(session):
    from app.models import MetricSample

    target = date(2026, 5, 23)
    jst = ZoneInfo("Asia/Tokyo")
    wake = datetime.combine(target, datetime.min.time(), jst).replace(hour=6, minute=30)
    # 1800 秒 = 30 分
    session.add(
        MetricSample(
            source="hae",
            metric_key="time_in_daylight",
            ts=(wake + timedelta(minutes=30)).astimezone(UTC).replace(tzinfo=None),
            value=1800.0,
            unit="s",
        )
    )
    session.flush()

    out = compute_morning_light_score(session, target)
    assert out["daylight_min"] == 30
    assert out["source"] == "apple_daylight"

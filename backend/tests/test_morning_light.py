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


def test_uses_actual_wake_when_detectable(session):
    """SleepSession.raw_json から体動起床を検出できれば、それを窓の起点にする
    (config の wake_hhmm=06:30 ではなく実起床の 07:10 を使う)。"""
    from app.models import MetricSample, SleepSession

    target = date(2026, 5, 23)
    jst = ZoneInfo("Asia/Tokyo")
    sleep_end_jst = datetime.combine(target, datetime.min.time(), jst).replace(hour=7, minute=0)
    actual_wake_jst = sleep_end_jst + timedelta(minutes=10)  # 布団 10分

    epoch_ms = int(sleep_end_jst.astimezone(UTC).timestamp() * 1000)

    def entry(dt, level):
        s = dt.astimezone(UTC).replace(tzinfo=None)
        e = s + timedelta(minutes=1)
        return {
            "startGMT": s.strftime("%Y-%m-%dT%H:%M:%S.0"),
            "endGMT": e.strftime("%Y-%m-%dT%H:%M:%S.0"),
            "activityLevel": level,
        }

    movement = [entry(sleep_end_jst + timedelta(minutes=i), 2.0) for i in range(10)]
    movement += [entry(actual_wake_jst + timedelta(minutes=i), 6.0) for i in range(3)]

    session.add(SleepSession(
        date=target, source="garmin", total_min=420,
        raw_json={
            "dailySleepDTO": {"sleepEndTimestampGMT": epoch_ms},
            "sleepMovement": movement,
        },
    ))
    # 実起床 (07:10) から window_hours=3h の窓の中に歩数を置く。
    # config 起床 (06:30) の窓なら拾えない時刻。
    session.add(
        MetricSample(
            source="garmin",
            metric_key="steps",
            ts=(actual_wake_jst + timedelta(minutes=5)).astimezone(UTC).replace(tzinfo=None),
            value=3000.0,
        )
    )
    session.flush()

    out = compute_morning_light_score(session, target, wake_hhmm="06:30")
    assert out["wake_source"] == "actual_wake"
    assert out["window_start_jst"] == actual_wake_jst.strftime("%H:%M")
    assert out["steps_in_window"] == 3000


def test_falls_back_to_wake_hhmm_when_no_movement_data(session):
    """sleepMovement が無い/検出不能な夜は wake_hhmm (目標起床時刻) にフォールバック。"""
    from app.models import SleepSession

    target = date(2026, 5, 23)
    session.add(SleepSession(date=target, source="garmin", total_min=420, raw_json=None))
    session.flush()

    out = compute_morning_light_score(session, target, wake_hhmm="06:30")
    assert out["wake_source"] == "target_wake_time"
    assert out["window_start_jst"] == "06:30"


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

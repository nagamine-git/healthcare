from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.scoring.wellbeing_alerts import evaluate_alerts


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


def test_no_alerts_with_empty_db(session):
    alerts = evaluate_alerts(session, date(2026, 5, 23))
    assert alerts == []


def test_chronic_sleep_deficit_triggers_critical(session):
    from app.models import SleepSession

    today = date(2026, 5, 23)
    # 3 日のうち 2 日が 4h 未満
    session.add(SleepSession(date=today, source="garmin", total_min=240))
    session.add(SleepSession(date=today - timedelta(days=1), source="garmin", total_min=240))
    session.add(SleepSession(date=today - timedelta(days=2), source="garmin", total_min=420))
    session.flush()

    alerts = evaluate_alerts(session, today)
    codes = [a.code for a in alerts]
    assert "chronic_sleep_deficit" in codes
    a = next(a for a in alerts if a.code == "chronic_sleep_deficit")
    assert a.severity == "critical"


def test_sleep_alert_not_triggered_when_only_one_short_night(session):
    from app.models import SleepSession

    today = date(2026, 5, 23)
    session.add(SleepSession(date=today, source="garmin", total_min=240))
    session.add(SleepSession(date=today - timedelta(days=1), source="garmin", total_min=420))
    session.add(SleepSession(date=today - timedelta(days=2), source="garmin", total_min=420))
    session.flush()

    alerts = evaluate_alerts(session, today)
    assert "chronic_sleep_deficit" not in [a.code for a in alerts]


def test_hrv_decline_triggers_warning(session):
    from app.models import HrvDaily

    today = date(2026, 5, 23)
    # 28 日 baseline ~ 60, 直近 7 日 ~ 40 (-33%)
    for i in range(8, 28):
        session.add(HrvDaily(date=today - timedelta(days=i), last_night_avg=60.0))
    for i in range(7):
        session.add(HrvDaily(date=today - timedelta(days=i), last_night_avg=40.0))
    session.flush()

    alerts = evaluate_alerts(session, today)
    codes = [a.code for a in alerts]
    assert "hrv_chronic_decline" in codes


def test_recovery_failure_triggers_warning(session):
    from app.models import BodyBatteryDaily

    today = date(2026, 5, 23)
    for i in range(3):
        session.add(
            BodyBatteryDaily(
                date=today - timedelta(days=i),
                morning_value=22.0,
                max_value=30,
                min_value=18,
                end_of_day=20,
            )
        )
    session.flush()

    alerts = evaluate_alerts(session, today)
    codes = [a.code for a in alerts]
    assert "recovery_failure" in codes


def test_weight_loss_triggers_critical(session):
    from app.models import WeightSample

    today = date(2026, 5, 23)
    # 目標下限 55.5kg - 1.0 = 54.5kg。中央値 54.0 で alert
    for i in range(5):
        session.add(
            WeightSample(
                ts=datetime.combine(today, datetime.min.time()) - timedelta(days=i),
                weight_kg=54.0,
                source="hae",
            )
        )
    session.flush()

    alerts = evaluate_alerts(session, today, target_weight_kg=56.5, weight_lower_kg=55.5)
    codes = [a.code for a in alerts]
    assert "weight_loss" in codes


def test_moh_high_when_12_or_more_painkillers(session):
    from app.models import CaffeineIntake

    today = date(2026, 5, 23)
    now = datetime.now(UTC).replace(tzinfo=None)
    for i in range(13):
        session.add(
            CaffeineIntake(
                ts=now - timedelta(days=i),
                source="ibuquick",
                amount=2.0,
                unit="錠",
                mg=80.0,
            )
        )
    session.flush()

    alerts = evaluate_alerts(session, today)
    codes = [a.code for a in alerts]
    assert "moh_risk_high" in codes


def test_moh_mid_when_8_to_11(session):
    from app.models import CaffeineIntake

    today = date(2026, 5, 23)
    now = datetime.now(UTC).replace(tzinfo=None)
    for i in range(9):
        session.add(
            CaffeineIntake(
                ts=now - timedelta(days=i),
                source="bufferin_premium",
                amount=2.0,
                unit="錠",
                mg=80.0,
            )
        )
    session.flush()

    alerts = evaluate_alerts(session, today)
    codes = [a.code for a in alerts]
    assert "moh_risk_mid" in codes


def test_caffeine_dependency_cycle(session):
    from app.models import CaffeineIntake, SleepSession

    today = date(2026, 5, 23)
    now = datetime.now(UTC).replace(tzinfo=None)
    # 直近 7 日 sleep 5h 平均
    for i in range(7):
        session.add(
            SleepSession(
                date=today - timedelta(days=i),
                source="garmin",
                total_min=300,
            )
        )
    # 直近 7 日 caffeine 1800mg (1日 ~257mg)
    for i in range(9):
        session.add(
            CaffeineIntake(
                ts=now - timedelta(hours=i * 18),
                source="canned_coffee",
                amount=1.0,
                unit="本",
                mg=200.0,
            )
        )
    session.flush()

    alerts = evaluate_alerts(session, today)
    codes = [a.code for a in alerts]
    assert "caffeine_dependency_cycle" in codes


def test_pressure_migraine_trigger(session):
    from app.models import MigraineEpisode

    today = date(2026, 5, 23)
    now = datetime.now(UTC).replace(tzinfo=None)
    for i in range(4):
        session.add(
            MigraineEpisode(
                started_at=now - timedelta(days=i * 5),
                ended_at=now - timedelta(days=i * 5, hours=-3),
                severity=6,
            )
        )
    session.flush()

    alerts = evaluate_alerts(session, today, pressure_risk_level="severe")
    codes = [a.code for a in alerts]
    assert "pressure_migraine_trigger" in codes
    a = next(a for a in alerts if a.code == "pressure_migraine_trigger")
    assert a.severity == "critical"


def test_alerts_sorted_by_severity(session):
    from app.models import HrvDaily, SleepSession

    today = date(2026, 5, 23)
    # sleep critical
    session.add(SleepSession(date=today, source="garmin", total_min=240))
    session.add(SleepSession(date=today - timedelta(days=1), source="garmin", total_min=240))
    # hrv warning
    for i in range(8, 28):
        session.add(HrvDaily(date=today - timedelta(days=i), last_night_avg=60.0))
    for i in range(7):
        session.add(HrvDaily(date=today - timedelta(days=i), last_night_avg=40.0))
    session.flush()

    alerts = evaluate_alerts(session, today)
    severities = [a.severity for a in alerts]
    # critical が warning より前
    if "critical" in severities and "warning" in severities:
        assert severities.index("critical") < severities.index("warning")

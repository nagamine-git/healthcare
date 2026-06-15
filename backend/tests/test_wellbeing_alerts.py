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


def test_weight_loss_triggers_when_underweight(session):
    """BMI 18.5 健康下限 (例 50.4kg) を下回ったら低体重アラート。"""
    from app.models import WeightSample

    today = date(2026, 5, 23)
    for i in range(5):
        session.add(
            WeightSample(
                ts=datetime.combine(today, datetime.min.time()) - timedelta(days=i),
                weight_kg=49.5,  # BMI 18.5 floor 50.4 を下回る
                source="hae",
            )
        )
    session.flush()

    alerts = evaluate_alerts(session, today, target_weight_kg=55.0, weight_lower_kg=50.4)
    codes = [a.code for a in alerts]
    assert "weight_loss" in codes


def test_weight_loss_no_alert_when_below_gain_target_but_healthy(session):
    """増量目標 (59kg) に未達でも、BMI が健康域なら誤発火しない。"""
    from app.models import WeightSample

    today = date(2026, 5, 23)
    for i in range(5):
        session.add(
            WeightSample(
                ts=datetime.combine(today, datetime.min.time()) - timedelta(days=i),
                weight_kg=54.6,  # BMI 20.0、健康域。floor 50.4 より上
                source="hae",
            )
        )
    session.flush()

    alerts = evaluate_alerts(session, today, target_weight_kg=59.0, weight_lower_kg=50.4)
    codes = [a.code for a in alerts]
    assert "weight_loss" not in codes


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


def test_moh_counts_distinct_days_not_doses(session):
    """同じ日に複数回服用しても 1 日として数える (ICHD-3 は服用日数基準)。"""
    from app.models import CaffeineIntake

    today = date(2026, 5, 23)
    now = datetime.now(UTC).replace(tzinfo=None)
    # 4 日間、各日 5 錠ずつ = 20 レコードだが 4 日 → どの MOH 域にも入らない
    for day in range(4):
        for dose in range(5):
            session.add(
                CaffeineIntake(
                    ts=now - timedelta(days=day, hours=dose),
                    source="ibuquick",
                    amount=1.0,
                    unit="錠",
                    mg=40.0,
                )
            )
    session.flush()

    alerts = evaluate_alerts(session, today)
    codes = [a.code for a in alerts]
    assert "moh_risk_high" not in codes
    assert "moh_risk_mid" not in codes


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


def test_moh_high_at_ichd3_threshold_10_days(session):
    """ICHD-3: カフェイン配合複合鎮痛薬は月10日が乱用域 → 10日でhigh (12日ではない)。"""
    from app.models import CaffeineIntake

    today = date(2026, 5, 23)
    now = datetime.now(UTC).replace(tzinfo=None)
    for i in range(10):
        session.add(CaffeineIntake(
            ts=now - timedelta(days=i), source="ibuquick", amount=2.0, unit="錠", mg=80.0))
    session.flush()
    codes = [a.code for a in evaluate_alerts(session, today)]
    assert "moh_risk_high" in codes
    assert "moh_risk_mid" not in codes


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


def _add_metric(session, key: str, target: date, value: float, days_ago: int = 0):
    from app.models import MetricSample

    d = target - timedelta(days=days_ago)
    ts = datetime.combine(d, datetime.min.time()).replace(hour=7)
    session.add(MetricSample(source="garmin", metric_key=key, ts=ts, value=value))


def test_sleep_spo2_low_triggers_warning(session):
    today = date(2026, 5, 23)
    # 直近 3 日中 2 日が avg < 93
    _add_metric(session, "sleep_spo2_avg", today, 91.0, 0)
    _add_metric(session, "sleep_spo2_avg", today, 92.0, 1)
    _add_metric(session, "sleep_spo2_avg", today, 95.0, 2)
    session.flush()
    alerts = evaluate_alerts(session, today)
    a = next((x for x in alerts if x.code == "sleep_spo2_low"), None)
    assert a is not None and a.severity == "warning"


def test_sleep_spo2_single_low_night_does_not_trigger(session):
    today = date(2026, 5, 23)
    _add_metric(session, "sleep_spo2_avg", today, 91.0, 0)
    _add_metric(session, "sleep_spo2_avg", today, 96.0, 1)
    _add_metric(session, "sleep_spo2_avg", today, 96.0, 2)
    session.flush()
    alerts = evaluate_alerts(session, today)
    assert all(a.code != "sleep_spo2_low" for a in alerts)


def test_sleep_spo2_window_is_exactly_3_nights(session):
    """4 夜前の古い低値が「直近 3 夜」判定に混入しない (off-by-one 回帰)。

    実例: 直近 3 夜の最低値 86/84/78 (該当 1 夜のみ) なのに、4 夜前の 72 が
    窓に入って「2 夜以上 <80%」と誤発火し、表示値とアラートが食い違った。
    """
    today = date(2026, 5, 23)
    for i in range(3):
        _add_metric(session, "sleep_spo2_avg", today, 96.0, i)
    _add_metric(session, "sleep_spo2_lowest", today, 86.0, 0)
    _add_metric(session, "sleep_spo2_lowest", today, 84.0, 1)
    _add_metric(session, "sleep_spo2_lowest", today, 78.0, 2)  # <80 はこの 1 夜だけ
    _add_metric(session, "sleep_spo2_lowest", today, 72.0, 3)  # 4 夜前 → 窓外
    session.flush()
    alerts = evaluate_alerts(session, today)
    assert all(a.code != "sleep_spo2_low" for a in alerts)


def test_sleep_spo2_low_via_lowest_desaturation(session):
    """平均は正常でも最低値が複数夜 80% 未満なら無呼吸スクリーニングで発火。"""
    today = date(2026, 5, 23)
    for i in range(3):
        _add_metric(session, "sleep_spo2_avg", today, 95.0, i)  # avg は正常
    _add_metric(session, "sleep_spo2_lowest", today, 78.0, 0)
    _add_metric(session, "sleep_spo2_lowest", today, 79.0, 1)
    _add_metric(session, "sleep_spo2_lowest", today, 88.0, 2)
    session.flush()
    alerts = evaluate_alerts(session, today)
    a = next((x for x in alerts if x.code == "sleep_spo2_low"), None)
    assert a is not None


def test_respiration_elevated_vs_baseline(session):
    today = date(2026, 5, 23)
    # 28 日 baseline ~13、直近 3 日が +2 以上
    for i in range(4, 28):
        _add_metric(session, "sleep_respiration_avg", today, 13.0, i)
    for i in range(3):
        _add_metric(session, "sleep_respiration_avg", today, 15.5, i)
    session.flush()
    alerts = evaluate_alerts(session, today)
    a = next((x for x in alerts if x.code == "respiration_elevated"), None)
    assert a is not None and a.severity == "info"


def test_readiness_low_streak(session):
    today = date(2026, 5, 23)
    for i in range(3):
        _add_metric(session, "training_readiness", today, 25.0, i)
    session.flush()
    alerts = evaluate_alerts(session, today)
    a = next((x for x in alerts if x.code == "readiness_low_streak"), None)
    assert a is not None and a.severity == "warning"


def test_sleep_irregular_midpoint(session):
    today = date(2026, 5, 23)
    # 中点が 1:00 と 5:00 を交互 → SD ≈ 2h
    for i in range(14):
        _add_metric(session, "sleep_midpoint_hour", today, 1.0 if i % 2 == 0 else 5.0, i)
    session.flush()
    alerts = evaluate_alerts(session, today)
    a = next((x for x in alerts if x.code == "sleep_irregular"), None)
    assert a is not None and a.severity == "info"

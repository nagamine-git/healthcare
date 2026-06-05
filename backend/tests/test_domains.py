from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db import session_scope
from app.models import MetricSample, SleepSession, WeightSample, Workout


def test_meditation_achievement(db_engine):
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    today = date(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=start, value=10.0))
    # 目標 15 分 → 10/15 → upper(10,0,15) ≈ 66.7
    a = domains.meditation_achievement(today)
    assert a is not None and 60 <= a <= 75


def test_meditation_counts_breathwork_workout(db_engine):
    """Garmin の breathwork ワークアウトも瞑想分としてカウントする。"""
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    today = date(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(Workout(id="bw-1", source="garmin", start=start + timedelta(hours=8),
                      type="breathwork", duration_s=600))
    # 600s = 10分 → upper(10,0,15) ≈ 66.7
    assert domains.meditation_minutes(today) == 10.0
    a = domains.meditation_achievement(today)
    assert a is not None and 60 <= a <= 75


def test_meditation_sums_mindful_and_breathwork(db_engine):
    """mindful_minutes (HAE) と breathwork (garmin) は合算する。"""
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    today = date(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=start, value=5.0))
        s.add(Workout(id="bw-2", source="garmin", start=start + timedelta(hours=8),
                      type="breathwork", duration_s=600))
    # 5 + 10 = 15分 → 目標15分 → 100点
    assert domains.meditation_minutes(today) == 15.0
    assert domains.meditation_achievement(today) == 100.0


def test_meditation_none_when_no_data(db_engine):
    from app.scoring import domains

    assert domains.meditation_achievement(date(2026, 5, 20)) is None


def test_health_achievement_averages(db_engine):
    from app.scoring import domains

    today = date(2026, 5, 20)
    with session_scope() as s:
        for i in range(3):
            d = today - timedelta(days=i)
            s.add(SleepSession(date=d, source="garmin", total_min=480, sleep_score=80))
            s.add(WeightSample(ts=datetime.combine(d, datetime.min.time()),
                               weight_kg=56.5, body_fat_pct=14.0, source="hae"))
    a = domains.health_achievement(today)
    assert a is not None and 0 <= a <= 100


def test_compute_life_weighted(db_engine):
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    today = date(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=start, value=15.0))  # 100点
        s.add(SleepSession(date=today, source="garmin", total_min=480, sleep_score=80))
        s.add(WeightSample(ts=datetime.combine(today, datetime.min.time()),
                           weight_kg=56.5, body_fat_pct=14.0, source="hae"))
    out = domains.compute_life(today, {"health": 1.0, "meditation": 3.0})
    assert out["life_score"] is not None
    assert {d["key"] for d in out["domains"]} == {"health", "meditation", "speech", "learning", "work"}
    med = next(d for d in out["domains"] if d["key"] == "meditation")
    assert med["achievement"] == 100.0
    assert med["weight"] == 3.0

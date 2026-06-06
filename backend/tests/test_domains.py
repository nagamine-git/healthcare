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


def test_domain_last_data(db_engine):
    """ドメイン単位の最終データ日。ソース死活では中身の途絶を検出できないため。"""
    from app.models import ExternalDomainEntry, Workout
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    old_day = date(2026, 1, 4)
    new_day = date(2026, 5, 20)
    old_start, _ = jst_day_bounds(old_day)
    new_start, _ = jst_day_bounds(new_day)
    with session_scope() as s:
        # 瞑想: mindful_minutes は古く、breathwork が新しい → 新しい方を採用
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=old_start, value=3.0))
        s.add(Workout(id="bw-ld", source="garmin", start=new_start + timedelta(hours=8),
                      type="breathwork", duration_s=300))
        s.add(ExternalDomainEntry(domain="learning", date=old_day, achievement=60.0))
    assert domains.domain_last_data("meditation") == new_day
    assert domains.domain_last_data("learning") == old_day
    assert domains.domain_last_data("work") is None  # データ未受信


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


def test_compute_life_weight_scales_expectation(db_engine):
    """重み＝期待水準: achievement は min(100, 生達成度/weight) に補正される。"""
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    today = date(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        # 7.5分 → 生達成度 50 (目標15分)
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=start, value=7.5))
    out = domains.compute_life(today, {"meditation": 0.5})
    med = next(d for d in out["domains"] if d["key"] == "meditation")
    assert med["raw_achievement"] == 50.0
    assert med["achievement"] == 100.0  # 50 / 0.5 → 100 (期待半分なら満点)
    assert med["weight"] == 0.5


def test_compute_life_weight_above_one_caps(db_engine):
    """weight > 1 は要求が上がる: 生100点でも 100/weight 止まり。"""
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    today = date(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=start, value=15.0))
    out = domains.compute_life(today, {"meditation": 2.0})
    med = next(d for d in out["domains"] if d["key"] == "meditation")
    assert med["raw_achievement"] == 100.0
    assert med["achievement"] == 50.0


def test_compute_life_simple_mean(db_engine):
    """ライフスコアは補正後スコアの単純平均 (null は除外)。"""
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    today = date(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=start, value=7.5))
        s.add(SleepSession(date=today, source="garmin", total_min=480, sleep_score=80))
        s.add(WeightSample(ts=datetime.combine(today, datetime.min.time()),
                           weight_kg=56.5, body_fat_pct=14.0, source="hae"))
    out = domains.compute_life(today, {"health": 1.0, "meditation": 0.5})
    med = next(d for d in out["domains"] if d["key"] == "meditation")
    health = next(d for d in out["domains"] if d["key"] == "health")
    assert med["achievement"] == 100.0
    # 単純平均 (speech/learning/work は null で除外)
    expected = round((health["achievement"] + med["achievement"]) / 2, 2)
    assert out["life_score"] == expected


def test_compute_life_weight_zero_excluded(db_engine):
    """weight=0 のドメインは集計から除外され、achievement は生値のまま。"""
    from app.scoring import domains
    from app.scoring.timewindow import jst_day_bounds

    today = date(2026, 5, 20)
    start, _ = jst_day_bounds(today)
    with session_scope() as s:
        s.add(MetricSample(source="hae", metric_key="mindful_minutes", ts=start, value=7.5))
        s.add(SleepSession(date=today, source="garmin", total_min=480, sleep_score=80))
        s.add(WeightSample(ts=datetime.combine(today, datetime.min.time()),
                           weight_kg=56.5, body_fat_pct=14.0, source="hae"))
    out = domains.compute_life(today, {"health": 1.0, "meditation": 0.0})
    med = next(d for d in out["domains"] if d["key"] == "meditation")
    health = next(d for d in out["domains"] if d["key"] == "health")
    assert med["achievement"] == 50.0  # 生値のまま
    assert out["life_score"] == health["achievement"]  # 瞑想は集計外

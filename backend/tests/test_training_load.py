from __future__ import annotations

from datetime import UTC, date, datetime

from app.scoring.recompute import _acwr, _daily_loads, _workout_load


def test_workout_load_uses_training_load_when_present():
    assert _workout_load(50.0, 1800) == 50.0


def test_workout_load_falls_back_to_minutes_when_training_load_missing():
    # training_load 欠損(None / 0)のワークアウトも時間(分)で負荷計上する。
    # 以前は ACWR 側で 0 扱いになり、在宅・自重トレで急性負荷が過小評価されていた。
    assert _workout_load(None, 1800) == 30.0
    assert _workout_load(0.0, 1800) == 30.0


def test_workout_load_zero_when_no_data():
    assert _workout_load(None, None) == 0.0


def test_daily_loads_counts_load_missing_workout():
    target = date(2026, 6, 20)
    # JST 6/20 06:00 のワークアウト (UTC 6/19 21:00)、training_load 欠損、30分。
    workouts = [(datetime(2026, 6, 19, 21, 0, tzinfo=UTC), None, 1800)]
    series = _daily_loads(workouts, target)
    assert len(series) == 42
    assert series[-1] == 30.0  # target 当日に 30 の負荷が立つ(以前は 0 だった)


def test_daily_loads_sums_same_day_workouts():
    target = date(2026, 6, 20)
    workouts = [
        (datetime(2026, 6, 19, 21, 0, tzinfo=UTC), 20.0, None),
        (datetime(2026, 6, 20, 3, 0, tzinfo=UTC), 10.0, None),  # JST 同日 12:00
    ]
    series = _daily_loads(workouts, target)
    assert series[-1] == 30.0


def test_acwr_equal_when_load_is_constant():
    series = [10.0] * 42
    acute, chronic = _acwr(series)
    assert acute is not None and chronic is not None
    assert abs(acute - 10.0) < 0.5
    assert abs(chronic - 10.0) < 0.5


def test_acute_exceeds_chronic_on_recent_spike():
    # 直近だけ高負荷 → 急性(span7)が慢性(span28)より強く反応し ACWR>1 になる。
    series = [2.0] * 39 + [20.0] * 3
    acute, chronic = _acwr(series)
    assert acute is not None and chronic is not None
    assert acute > chronic

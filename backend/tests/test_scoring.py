from __future__ import annotations

import math

import pytest

from app.scoring.baselines import Baseline, build_baseline, ewma
from app.scoring.composite import composite_score
from app.scoring.subscores import (
    body_battery_subscore,
    body_fat_subscore,
    hrv_subscore,
    sleep_subscore,
    training_load_subscore,
    weight_subscore,
)

# ----- helpers -----


def approx(value: float, tol: float = 0.5) -> pytest.approx:  # type: ignore[valid-type]
    return pytest.approx(value, abs=tol)


# ----- baseline -----


def test_build_baseline_uses_window_mean_and_std():
    values = [50.0, 52.0, 48.0, 51.0, 49.0]
    baseline = build_baseline(values)
    assert baseline.mean == approx(50.0)
    assert baseline.std > 0
    assert baseline.n == 5


def test_build_baseline_with_empty_returns_none():
    assert build_baseline([]) is None


def test_build_baseline_filters_nones():
    values = [50.0, None, 52.0, None, 48.0]
    baseline = build_baseline(values)
    assert baseline is not None
    assert baseline.n == 3


def test_ewma_short_horizon_emphasises_recent():
    short = ewma([10, 10, 10, 100], span=2)
    long = ewma([10, 10, 10, 100], span=4)
    assert short > long


def test_ewma_returns_none_on_empty():
    assert ewma([], span=7) is None


# ----- sleep -----


def test_sleep_subscore_uses_garmin_score_when_available():
    assert sleep_subscore(garmin_sleep_score=82.0, total_min=None) == 82.0


def test_sleep_subscore_clamps_garmin_score():
    assert sleep_subscore(garmin_sleep_score=110.0, total_min=None) == 100.0
    assert sleep_subscore(garmin_sleep_score=-5.0, total_min=None) == 0.0


def test_sleep_subscore_falls_back_to_duration_when_no_score():
    # 7.5h sleep, 88% efficiency, 25% deep+rem
    s = sleep_subscore(
        garmin_sleep_score=None,
        total_min=450,
        deep_min=70,
        rem_min=80,
        light_min=270,
        awake_min=30,
    )
    assert 60 <= s <= 100


def test_sleep_subscore_returns_none_when_no_data():
    assert sleep_subscore(garmin_sleep_score=None, total_min=None) is None


# ----- HRV -----


def test_hrv_subscore_returns_50_at_baseline_mean():
    bl = Baseline(mean=60.0, std=5.0, n=28)
    assert hrv_subscore(60.0, bl) == approx(50.0, tol=1)


def test_hrv_subscore_increases_with_higher_hrv():
    bl = Baseline(mean=60.0, std=5.0, n=28)
    assert hrv_subscore(70.0, bl) > hrv_subscore(60.0, bl)
    assert hrv_subscore(70.0, bl) == approx(100.0, tol=2)  # +2σ → 100


def test_hrv_subscore_decreases_with_lower_hrv():
    bl = Baseline(mean=60.0, std=5.0, n=28)
    assert hrv_subscore(50.0, bl) == approx(0.0, tol=2)  # -2σ → 0


def test_hrv_subscore_clamps():
    bl = Baseline(mean=60.0, std=5.0, n=28)
    assert hrv_subscore(40.0, bl) == 0.0
    assert hrv_subscore(80.0, bl) == 100.0


def test_hrv_subscore_returns_none_when_baseline_missing():
    assert hrv_subscore(60.0, None) is None


def test_hrv_subscore_returns_none_when_value_missing():
    bl = Baseline(mean=60.0, std=5.0, n=28)
    assert hrv_subscore(None, bl) is None


# ----- body battery -----


def test_body_battery_subscore_passes_through_morning_value():
    assert body_battery_subscore(morning_value=88.0) == 88.0


def test_body_battery_subscore_clamps():
    assert body_battery_subscore(morning_value=110.0) == 100.0
    assert body_battery_subscore(morning_value=-5.0) == 0.0


def test_body_battery_subscore_none():
    assert body_battery_subscore(morning_value=None) is None


# ----- training load -----


def test_training_load_optimal_zone():
    # acute = chronic ⇒ ratio 1.0 ⇒ optimal
    assert training_load_subscore(acute=100, chronic=100) == 85.0


def test_training_load_yellow_zone_low():
    # ratio 0.6 → yellow
    assert training_load_subscore(acute=60, chronic=100) == 65.0


def test_training_load_yellow_zone_high():
    # ratio 1.4
    assert training_load_subscore(acute=140, chronic=100) == 65.0


def test_training_load_red_zone():
    # ratio 1.8
    assert training_load_subscore(acute=180, chronic=100) == 40.0
    assert training_load_subscore(acute=20, chronic=100) == 40.0


def test_training_load_returns_none_when_chronic_zero():
    assert training_load_subscore(acute=10, chronic=0) is None


def test_training_load_returns_none_on_missing():
    assert training_load_subscore(acute=None, chronic=100) is None


# ----- weight -----


def test_weight_subscore_returns_80_when_within_one_sigma():
    bl = Baseline(mean=70.0, std=0.5, n=28)
    s = weight_subscore(recent_median=70.2, baseline=bl)
    assert s == 80.0


def test_weight_subscore_returns_50_at_two_sigma():
    bl = Baseline(mean=70.0, std=0.5, n=28)
    s = weight_subscore(recent_median=71.5, baseline=bl)  # +3σ → 30
    assert s == 30.0


def test_weight_subscore_returns_50_just_outside_one_sigma():
    bl = Baseline(mean=70.0, std=0.5, n=28)
    s = weight_subscore(recent_median=70.8, baseline=bl)  # +1.6σ → 50
    assert s == 50.0


def test_weight_subscore_none():
    assert weight_subscore(recent_median=None, baseline=Baseline(70.0, 0.5, 28)) is None
    assert weight_subscore(recent_median=70.0, baseline=None) is None


# ----- body fat -----


def test_body_fat_at_target():
    assert body_fat_subscore(recent_value=14.0, target_pct=14.0, tolerance_pct=1.5) == 90.0


def test_body_fat_within_one_tolerance():
    assert body_fat_subscore(recent_value=15.4, target_pct=14.0, tolerance_pct=1.5) == 90.0


def test_body_fat_within_two_tolerance():
    assert body_fat_subscore(recent_value=16.5, target_pct=14.0, tolerance_pct=1.5) == 75.0


def test_body_fat_within_three_tolerance():
    assert body_fat_subscore(recent_value=18.0, target_pct=14.0, tolerance_pct=1.5) == 55.0


def test_body_fat_far_from_target():
    assert body_fat_subscore(recent_value=22.0, target_pct=14.0, tolerance_pct=1.5) == 40.0


def test_body_fat_under_target_treated_same():
    """過剰に絞った場合も罰する (=低スコア寄り) ことで仕事パフォーマンス保護。"""
    assert body_fat_subscore(recent_value=10.0, target_pct=14.0, tolerance_pct=1.5) == 55.0


def test_body_fat_none():
    assert body_fat_subscore(recent_value=None, target_pct=14.0) is None
    assert body_fat_subscore(recent_value=14.0, target_pct=0.0) is None


# ----- composite -----


WEIGHTS = {"sleep": 3.0, "hrv": 2.0, "bb": 2.0, "load": 2.0, "weight": 1.0}


def test_composite_score_geometric_mean_of_equal_subs_is_same():
    sub = {"sleep": 80.0, "hrv": 80.0, "bb": 80.0, "load": 80.0, "weight": 80.0}
    assert composite_score(sub, WEIGHTS) == approx(80.0, tol=0.01)


def test_composite_score_drags_with_low_subscore():
    sub = {"sleep": 30.0, "hrv": 80.0, "bb": 80.0, "load": 80.0, "weight": 80.0}
    score = composite_score(sub, WEIGHTS)
    # Geometric mean is dragged down more than arithmetic
    arithmetic = (3 * 30 + 2 * 80 + 2 * 80 + 2 * 80 + 80) / 10
    assert score < arithmetic


def test_composite_score_skips_none_subs_and_renormalises():
    sub = {"sleep": 80.0, "hrv": None, "bb": 80.0, "load": 80.0, "weight": 80.0}
    s = composite_score(sub, WEIGHTS)
    assert s == approx(80.0, tol=0.01)


def test_composite_score_returns_none_if_all_subs_none():
    sub = {"sleep": None, "hrv": None, "bb": None, "load": None, "weight": None}
    assert composite_score(sub, WEIGHTS) is None


def test_composite_score_handles_zero_with_floor():
    sub = {"sleep": 0.0, "hrv": 80.0, "bb": 80.0, "load": 80.0, "weight": 80.0}
    s = composite_score(sub, WEIGHTS)
    # Geometric mean with a zero would be zero; we clamp to a tiny floor instead.
    assert s is not None
    assert s < 50.0
    assert math.isfinite(s)

from __future__ import annotations

from app.scoring import achievement as ach


def test_band_inside_is_100():
    assert ach.band_achievement(480, 420, 540, 90) == 100.0
    assert ach.band_achievement(420, 420, 540, 90) == 100.0


def test_band_half_at_softness():
    # 帯端から softness 離れると ~50
    v = ach.band_achievement(540 + 90, 420, 540, 90)
    assert 49.0 <= v <= 51.0


def test_band_symmetric():
    lo, hi, s = 420, 540, 90
    assert abs(ach.band_achievement(lo - 45, lo, hi, s) - ach.band_achievement(hi + 45, lo, hi, s)) < 1e-9


def test_upper_bounds():
    assert ach.upper_achievement(10, 20, 80) == 0.0
    assert ach.upper_achievement(80, 20, 80) == 100.0
    assert ach.upper_achievement(50, 20, 80) == 50.0


def test_sleep_quality_weighted():
    # 時間は理想(480→time 100)、質40 → 0.4*100 + 0.6*40 = 64
    a = ach.sleep_achievement(total_min=480, garmin_sleep_score=40,
                              deep_min=None, rem_min=None, light_min=None, awake_min=None)
    assert abs(a - 64.0) < 1e-6


def test_sleep_quality_missing_uses_time_only():
    a = ach.sleep_achievement(total_min=480, garmin_sleep_score=None,
                              deep_min=None, rem_min=None, light_min=None, awake_min=None)
    assert a == 100.0  # 質が無いので時間のみ(480 は帯中心)


def test_sleep_too_long_decays():
    a = ach.sleep_achievement(total_min=660, garmin_sleep_score=None,
                              deep_min=None, rem_min=None, light_min=None, awake_min=None)
    assert a < 60.0  # 11h は理想帯から大きく外れる


def test_hrv_achievement_clamps():
    from app.scoring.baselines import Baseline
    bl = Baseline(mean=60.0, std=10.0, n=28)
    assert ach.hrv_achievement(60.0, bl) == 50.0   # z=0
    assert ach.hrv_achievement(120.0, bl) == 100.0  # z>=2
    assert ach.hrv_achievement(0.0, bl) == 0.0      # z<=-2

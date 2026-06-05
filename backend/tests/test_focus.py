from __future__ import annotations

from datetime import datetime, time

import pytest

from app.scoring.baselines import Baseline
from app.scoring.focus import (
    circadian_factor,
    compute_focus_readiness,
    extract_peak_windows,
    predict_today_curve,
)


def approx(value: float, tol: float = 0.5) -> pytest.approx:  # type: ignore[valid-type]
    return pytest.approx(value, abs=tol)


# ----- circadian -----


def test_circadian_low_just_after_wake():
    # 06:30 起床、06:45 はまだ睡眠慣性
    assert circadian_factor(time(6, 45), wake=time(6, 30)) == approx(0.50, tol=0.01)


def test_circadian_peak_at_around_3h_after_wake():
    # +3h = 09:30 → 第1ピーク手前
    f = circadian_factor(time(9, 30), wake=time(6, 30))
    assert 0.85 <= f <= 1.0


def test_circadian_post_lunch_dip():
    # +7h = 13:30 → dip
    f = circadian_factor(time(13, 30), wake=time(6, 30))
    assert 0.60 <= f <= 0.80


def test_circadian_second_peak_late_afternoon():
    # +10h = 16:30 → 第2ピーク付近
    f = circadian_factor(time(16, 30), wake=time(6, 30))
    assert 0.75 <= f <= 0.95


def test_circadian_low_late_night():
    # +16h = 22:30 → 単調減少帯
    f = circadian_factor(time(22, 30), wake=time(6, 30))
    assert f <= 0.55


def test_circadian_floor():
    # 起床から 20h 以上経過しても 0.30 以上は保つ
    f = circadian_factor(time(2, 0), wake=time(6, 30))
    assert f >= 0.30


# ----- compute_focus_readiness -----


def test_focus_readiness_high_when_all_metrics_good():
    bl = Baseline(mean=50.0, std=5.0, n=28)
    fr = compute_focus_readiness(
        now=datetime(2026, 5, 14, 9, 30),  # +3h, 概日ピーク
        hrv_value=60.0,  # +2σ → 100
        hrv_baseline=bl,
        body_battery_current=85.0,
        stress_recent_avg=15.0,  # 100-15 = 85
        sleep_score=88.0,
        sleep_total_min=480,
        wake_time=time(6, 30),
    )
    assert fr.score is not None
    assert fr.score >= 70
    assert fr.level == "high"


def test_focus_readiness_low_with_bad_sleep_and_low_bb():
    bl = Baseline(mean=50.0, std=5.0, n=28)
    fr = compute_focus_readiness(
        now=datetime(2026, 5, 14, 14, 0),  # +7.5h, 食後の dip
        hrv_value=45.0,  # -1σ
        hrv_baseline=bl,
        body_battery_current=25.0,
        stress_recent_avg=70.0,  # 100-70 = 30
        sleep_score=40.0,
        sleep_total_min=300,
        wake_time=time(6, 30),
    )
    assert fr.score is not None
    assert fr.score < 50
    assert fr.level == "low"


def test_focus_readiness_handles_missing_components():
    fr = compute_focus_readiness(
        now=datetime(2026, 5, 14, 10, 0),
        hrv_value=None,
        hrv_baseline=None,
        body_battery_current=None,
        stress_recent_avg=None,
        sleep_score=None,
        sleep_total_min=None,
        wake_time=time(6, 30),
    )
    # 概日成分のみ残るので score は None ではない
    assert fr.score is not None
    assert fr.components.hrv is None
    assert fr.components.body_battery is None
    assert fr.components.stress is None
    assert fr.components.sleep is None
    assert fr.components.circadian is not None


def test_focus_readiness_rationale_mentions_worst():
    bl = Baseline(mean=50.0, std=5.0, n=28)
    fr = compute_focus_readiness(
        now=datetime(2026, 5, 14, 9, 30),
        hrv_value=60.0,
        hrv_baseline=bl,
        body_battery_current=20.0,  # 一番低い
        stress_recent_avg=15.0,
        sleep_score=90.0,
        sleep_total_min=480,
    )
    assert "Body Battery" in fr.rationale


# ----- curve / peak windows -----


def test_predict_today_curve_has_points_after_now():
    bl = Baseline(mean=50.0, std=5.0, n=28)
    curve = predict_today_curve(
        now=datetime(2026, 5, 14, 8, 0),
        hrv_value=55.0,
        hrv_baseline=bl,
        body_battery_current=80.0,
        stress_recent_avg=20.0,
        sleep_score=80.0,
        sleep_total_min=480,
        wake_time=time(6, 30),
    )
    assert len(curve) > 0
    # 全ポイントが 08:00 以降
    for p in curve:
        assert p["time"] >= "08:00"
    # 単調にスコアが減るとは限らない (概日で再上昇)
    scores = [float(p["score"]) for p in curve]
    assert min(scores) >= 0
    assert max(scores) <= 100


def test_extract_peak_windows_finds_high_score_runs():
    curve = [
        {"time": "09:00", "score": 70.0, "level": "high"},
        {"time": "09:30", "score": 72.0, "level": "high"},
        {"time": "10:00", "score": 68.0, "level": "high"},
        {"time": "10:30", "score": 50.0, "level": "mid"},
        {"time": "11:00", "score": 75.0, "level": "high"},
    ]
    windows = extract_peak_windows(curve, peak_threshold=65.0, min_duration_min=60)
    assert len(windows) == 1  # 09:00–10:00 (90 分) が拾われる、11:00 単独は短すぎ
    assert windows[0].start_hhmm == "09:00"
    assert windows[0].end_hhmm == "10:00"


def test_air_quality_pulls_focus_score_down():
    """PM2.5 が高いと Focus スコアが下がる (他条件同じ)。"""
    bl = Baseline(mean=50.0, std=5.0, n=28)
    base_args = dict(
        now=datetime(2026, 5, 23, 9, 30),
        hrv_value=55.0,
        hrv_baseline=bl,
        body_battery_current=80.0,
        stress_recent_avg=20.0,
        sleep_score=85.0,
        sleep_total_min=480,
        wake_time=time(6, 30),
    )
    from app.scoring.focus import compute_focus_readiness

    fr_clean = compute_focus_readiness(**base_args, pm2_5=5.0)
    fr_dirty = compute_focus_readiness(**base_args, pm2_5=80.0)
    assert fr_clean.score is not None
    assert fr_dirty.score is not None
    assert fr_dirty.score < fr_clean.score


def test_morning_light_high_boosts_focus():
    bl = Baseline(mean=50.0, std=5.0, n=28)
    base_args = dict(
        now=datetime(2026, 5, 23, 9, 30),
        hrv_value=55.0,
        hrv_baseline=bl,
        body_battery_current=80.0,
        stress_recent_avg=20.0,
        sleep_score=85.0,
        sleep_total_min=480,
        wake_time=time(6, 30),
    )
    from app.scoring.focus import compute_focus_readiness

    fr_dim = compute_focus_readiness(**base_args, morning_light_score=10.0)
    fr_bright = compute_focus_readiness(**base_args, morning_light_score=95.0)
    assert fr_bright.score > fr_dim.score


def test_extract_peak_windows_empty_when_no_peaks():
    curve = [
        {"time": "12:00", "score": 40.0, "level": "low"},
        {"time": "12:30", "score": 35.0, "level": "low"},
    ]
    assert extract_peak_windows(curve) == []

"""VO2Max 推定 (公表式) のテスト。数値は 2026-07-04 の実ラン。"""

from __future__ import annotations

from app.scoring.vo2max_estimate import acsm_submax_estimate, estimate_for_run, uth_estimate


def test_uth_with_real_numbers():
    # HRmax 183 (実測) / RHR 50 → 15.3×183/50 = 56.0
    assert uth_estimate(183, 50) == 56.0
    assert uth_estimate(0, 50) is None
    assert uth_estimate(100, 120) is None  # max <= rest は不正


def test_acsm_submax_with_real_numbers():
    # 歩数2512×ストライド0.9476m = 2380m / 15.3分 = 155.6 m/分
    # VO2 = 3.5+0.2×155.6 = 34.6, %HRR = (155-50)/(183-50) = 0.789 → 43.9前後
    v = acsm_submax_estimate(speed_m_min=155.6, avg_hr=155, hr_rest=50, hr_max=183)
    assert v is not None and 43.0 <= v <= 45.0
    # 楽すぎる運動 (%HRR<50%) からの外挿は拒否
    assert acsm_submax_estimate(speed_m_min=155.6, avg_hr=100, hr_rest=50, hr_max=183) is None
    # 歩行未満の速度は適用外
    assert acsm_submax_estimate(speed_m_min=50, avg_hr=155, hr_rest=50, hr_max=183) is None


def test_estimate_for_run_gps_missing_falls_back_to_steps():
    # 実ラン: GPS距離26m (不良) → 歩数×ストライドで速度を出す
    est = estimate_for_run(
        duration_s=918, avg_hr=155, hr_rest=50, hr_max=183,
        distance_m=26.6, steps=2512, stride_m=0.9476,
    )
    assert est is not None
    assert est["speed_source"] == "steps"
    assert set(est["methods"]) == {"uth", "acsm_submax"}
    assert est["low"] < est["mid"] < est["high"]
    assert 43.0 <= est["low"] <= 45.0 and 55.0 <= est["high"] <= 57.0


def test_estimate_for_run_uses_gps_when_valid():
    est = estimate_for_run(
        duration_s=1800, avg_hr=150, hr_rest=50, hr_max=183,
        distance_m=5000.0, steps=5000, stride_m=1.0,
    )
    assert est is not None and est["speed_source"] == "gps"


def test_estimate_requires_hr_basics():
    assert estimate_for_run(duration_s=918, avg_hr=155, hr_rest=None, hr_max=183) is None
    assert estimate_for_run(duration_s=918, avg_hr=155, hr_rest=50, hr_max=None) is None

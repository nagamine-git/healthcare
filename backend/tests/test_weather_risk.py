"""天気リスク (WBGT近似・降水) 純関数テスト。"""

from __future__ import annotations

from app.scoring.weather_risk import brief_from_hourly, heat_level, wbgt_approx


def test_heat_levels_follow_env_ministry_bands():
    assert heat_level(20) == "安全"
    assert heat_level(26) == "警戒"
    assert heat_level(29) == "厳重警戒"
    assert heat_level(32) == "危険"


def test_wbgt_humid_hotter_than_dry():
    # 同じ32℃でも湿度85%は乾燥30%よりWBGTが高い (熱中症リスク増)
    assert wbgt_approx(32, 85) > wbgt_approx(32, 30) + 3


def test_brief_flags_rain_heat_and_good_windows():
    hourly = [
        {"time": "2026-07-08T07:00", "temp_c": 24, "humidity": 60, "precip_prob": 10},
        {"time": "2026-07-08T12:00", "temp_c": 34, "humidity": 70, "precip_prob": 10},  # 危険域
        {"time": "2026-07-08T18:00", "temp_c": 27, "humidity": 65, "precip_prob": 70},  # 雨
    ]
    b = brief_from_hourly(hourly)
    assert "18:00" in b["rain_risk_times"]
    assert "12:00" in b["heat_caution_times"]
    assert "07:00" in b["good_outdoor_times"]

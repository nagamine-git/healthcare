from __future__ import annotations

from datetime import datetime

from app.integrations.weather_forecast import (
    _shape_forecast,
    laundry_hint,
    weather_code_to_label,
)


# --- WMO weathercode → 日本語ラベル + アイコンキー ---


def test_weather_code_clear_is_sun():
    label, icon = weather_code_to_label(0)
    assert icon == "sun"
    assert "晴" in label


def test_weather_code_partly_cloudy():
    assert weather_code_to_label(2)[1] == "cloud-sun"


def test_weather_code_overcast_is_cloud():
    assert weather_code_to_label(3)[1] == "cloud"


def test_weather_code_rain():
    assert weather_code_to_label(65)[1] == "rain"


def test_weather_code_snow():
    assert weather_code_to_label(71)[1] == "snow"


def test_weather_code_thunderstorm():
    assert weather_code_to_label(95)[1] == "storm"


def test_weather_code_unknown_for_none_and_garbage():
    assert weather_code_to_label(None)[1] == "unknown"
    assert weather_code_to_label(99999)[1] == "unknown"


# --- 洗濯/傘の素朴な3段判定 ---


def test_laundry_ok_when_dry():
    level, text = laundry_hint(prob_max=10, precip_total=0.0)
    assert level == "ok"
    assert text


def test_laundry_caution_on_mid_probability():
    assert laundry_hint(prob_max=45, precip_total=0.0)[0] == "caution"


def test_laundry_no_when_rain_likely():
    assert laundry_hint(prob_max=80, precip_total=3.0)[0] == "no"


def test_laundry_no_when_precip_present_even_if_prob_low():
    # 降水量が見込まれているなら確率が低くても干さない
    assert laundry_hint(prob_max=20, precip_total=1.5)[0] == "no"


def test_laundry_unknown_when_no_data():
    assert laundry_hint(prob_max=None, precip_total=None)[0] == "unknown"


# --- API生JSON → 整形 ---


def _raw():
    return {
        "hourly": {
            "time": ["2026-06-24T09:00", "2026-06-24T10:00", "2026-06-25T09:00"],
            "temperature_2m": [22.0, 23.0, 20.0],
            "precipitation": [0.0, 0.0, 1.2],
            "precipitation_probability": [10, 20, 70],
            "weathercode": [2, 3, 65],
            "relative_humidity_2m": [70, 72, 90],
            "wind_speed_10m": [5, 6, 4],
        },
        "daily": {
            "time": ["2026-06-24", "2026-06-25"],
            "weathercode": [3, 65],
            "temperature_2m_max": [26.0, 21.5],
            "temperature_2m_min": [18.0, 17.0],
            "precipitation_probability_max": [20, 98],
            "sunrise": ["2026-06-24T04:26", "2026-06-25T04:26"],
            "sunset": ["2026-06-24T19:00", "2026-06-25T19:00"],
        },
    }


def test_shape_forecast_builds_hourly():
    out = _shape_forecast(_raw(), datetime(2026, 6, 24, 8, 0))
    # now=08:00 以降の時間別(今日明日)
    assert len(out["hourly"]) == 3
    first = out["hourly"][0]
    assert first["temp"] == 22.0
    assert first["precip_prob"] == 10
    assert first["icon"] == "cloud-sun"  # code 2


def test_shape_forecast_drops_past_hours():
    out = _shape_forecast(_raw(), datetime(2026, 6, 24, 9, 30))
    # 09:00 は過去なので落ち、10:00 と翌日が残る
    assert out["hourly"][0]["time"].endswith("10:00")


def test_shape_forecast_builds_daily_week():
    out = _shape_forecast(_raw(), datetime(2026, 6, 24, 8, 0))
    assert len(out["daily"]) == 2
    assert out["daily"][1]["t_max"] == 21.5
    assert out["daily"][1]["precip_prob_max"] == 98


def test_shape_forecast_today_summary_with_laundry():
    out = _shape_forecast(_raw(), datetime(2026, 6, 24, 8, 0))
    s = out["summary"]
    assert s["t_max"] == 26.0
    assert s["t_min"] == 18.0
    assert s["laundry"]["level"] in ("ok", "caution", "no", "unknown")

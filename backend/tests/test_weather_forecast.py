from __future__ import annotations

from datetime import datetime

from app.integrations.weather_forecast import (
    _shape_forecast,
    laundry_advice,
    next_drying_window,
    weather_code_to_label,
)


def _fslot(dt, prob=5, precip=0.0, humidity=50, radiation=600, wind=2.0, gust=4.0):
    return {
        "dt": dt, "prob": prob, "precip": precip, "humidity": humidity,
        "radiation": radiation, "wind": wind, "gust": gust,
    }


def _diurnal(day, lo=6, hi=19):
    # 朝夕は弱く正午に強い、ざっくりした日射プロファイル。
    return [
        _fslot(datetime(2026, 6, 25, h, 0), radiation=max(0.0, 700 - abs(13 - h) * 90))
        for h in range(lo, hi)
    ]


def _slot(hour, prob, precip=0.0, temp=22.0, humidity=60.0, radiation=None, gust=None):
    # radiation=None は日射データ欠損 → 乾燥力判定をスキップ (雨だけで判定) する既存挙動。
    return {
        "hour": hour, "prob": prob, "precip": precip, "temp": temp,
        "humidity": humidity, "radiation": radiation, "gust": gust,
    }


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


# --- 洗濯の最適時間帯アドバイス ---


def test_laundry_all_clear_window_from_now():
    slots = [_slot(h, 5) for h in range(6, 19)]
    a = laundry_advice(slots, now_hour=9)
    assert a["level"] == "ok"
    assert a["can_now"] is True
    assert a["window"] == {"start": "09:00", "end": "19:00"}


def test_laundry_window_ends_before_afternoon_rain():
    slots = [_slot(h, 10) for h in range(6, 13)] + [
        _slot(h, 80, precip=1.0) for h in range(13, 19)
    ]
    a = laundry_advice(slots, now_hour=8)
    assert a["window"] == {"start": "08:00", "end": "13:00"}
    assert a["can_now"] is True


def test_laundry_all_rain_no_window():
    slots = [_slot(h, 90, precip=2.0) for h in range(6, 19)]
    a = laundry_advice(slots, now_hour=10)
    assert a["level"] == "no"
    assert a["can_now"] is False
    assert a["window"] is None


def test_laundry_night_has_no_window():
    slots = [_slot(h, 5) for h in range(6, 19)]
    a = laundry_advice(slots, now_hour=20)
    assert a["can_now"] is False
    assert a["window"] is None


def test_laundry_short_window_is_caution():
    slots = (
        [_slot(h, 90, precip=1.0) for h in range(6, 17)]
        + [_slot(17, 10), _slot(18, 10)]
    )
    a = laundry_advice(slots, now_hour=16)
    assert a["window"]["start"] == "17:00"
    assert a["level"] == "caution"


def test_laundry_high_prob_light_drizzle_is_not_dry():
    # 降水確率が高ければ微量(0.3mm)でも「干せる」にしない (量が絶対ではない)。
    slots = [_slot(h, 85, precip=0.3) for h in range(6, 19)]
    a = laundry_advice(slots, now_hour=9)
    assert a["can_now"] is False
    assert a["window"] is None
    assert a["level"] == "no"


def test_laundry_moderate_prob_trace_is_caution_window():
    # 中程度の確率(45%)・微量(0.2mm)は「干せるが注意」で窓に含む。
    slots = [_slot(h, 45, precip=0.2) for h in range(6, 19)]
    a = laundry_advice(slots, now_hour=9)
    assert a["window"] is not None
    assert "注意" in a["window_text"]
    assert a["now_text"].startswith("今は干せるが")


def test_laundry_evening_low_sun_excluded_from_window():
    # 日中(9-16時)は晴れて乾くが、夕方(17-18時)は日射不足。雨は降らなくても
    # 乾かないので狙い目に含めない (18:00〜19:00 のような無意味な窓を出さない)。
    slots = (
        [_slot(h, 5, radiation=600) for h in range(9, 16)]
        + [_slot(16, 5, radiation=200)]  # まだ乾く
        + [_slot(17, 5, radiation=60), _slot(18, 5, radiation=20)]  # 日射不足
    )
    a = laundry_advice(slots, now_hour=9)
    assert a["window"]["start"] == "09:00"
    assert a["window"]["end"] == "17:00"  # 16時まで (17:00 は end 排他) で打ち切り


def test_laundry_now_low_sun_message():
    # 雨は降らない(prob5)が今(18時)は日射ほぼ無し → 干せるが乾きにくい。
    a = laundry_advice([_slot(18, 5, radiation=20)], now_hour=18)
    assert a["can_now"] is False
    assert "乾きにくい" in a["now_text"]


def test_laundry_midday_good_sun_is_ok():
    slots = [_slot(h, 5, radiation=600, humidity=50) for h in range(10, 15)]
    a = laundry_advice(slots, now_hour=10)
    assert a["level"] == "ok"
    assert a["can_now"] is True


def test_laundry_prefers_lower_rain_window_on_tie():
    # 同じ長さの窓が2つ: 朝(微量雨で注意)と夕方(完全乾燥)。雨量の少ない夕方を選ぶ。
    slots = (
        [_slot(h, 45, precip=0.2) for h in range(6, 9)]  # 注意 3h
        + [_slot(h, 95, precip=3.0) for h in range(9, 13)]  # 不可で分断
        + [_slot(h, 5, precip=0.0) for h in range(13, 16)]  # 乾燥 3h
        + [_slot(h, 95, precip=3.0) for h in range(16, 19)]
    )
    a = laundry_advice(slots, now_hour=6)
    assert a["window"] == {"start": "13:00", "end": "16:00"}
    assert a["level"] == "ok"  # 乾燥3hなので ok


def test_laundry_strong_gust_blocks_now():
    # 晴れて乾く条件でも、突風(12m/s)なら飛ぶので「今は不可」。
    a = laundry_advice([_slot(11, 5, radiation=600, gust=12.0)], now_hour=11)
    assert a["can_now"] is False
    assert "強風" in a["now_text"]


def test_laundry_moderate_gust_is_caution_now():
    a = laundry_advice([_slot(11, 5, radiation=600, gust=9.0)], now_hour=11)
    assert "強風注意" in a["now_text"]


# --- 次に干せるベスト時刻 (分単位) の推定 ---


def test_next_drying_window_sunny_returns_minutewise_window():
    slots = _diurnal(2026)
    now = datetime(2026, 6, 25, 7, 30)
    nxt = next_drying_window(slots, now)
    assert nxt is not None
    assert nxt["minutes"] > 0
    assert nxt["within_5h"] is True  # 晴天なので5時間以内に乾く
    # 開始は分単位 (HH:MM)。朝の好機なので 7:30 以降。
    assert nxt["start"] >= "07:30"
    assert nxt["dry_by"] > nxt["start"]


def test_next_drying_window_cloudy_no_window():
    # 終日 曇天 (日射120 → 乾燥力不足) → 乾く窓なし。
    slots = [_fslot(datetime(2026, 6, 25, h, 0), radiation=120) for h in range(6, 19)]
    now = datetime(2026, 6, 25, 9, 0)
    assert next_drying_window(slots, now) is None


def test_next_drying_window_rolls_to_next_morning_at_night():
    # 夜(22時)から開始。今日の日射はもう無く、翌日の日中に乾く窓を返す。
    day1 = [_fslot(datetime(2026, 6, 25, h, 0), radiation=0.0) for h in range(20, 24)]
    day2 = [
        _fslot(datetime(2026, 6, 26, h, 0), radiation=max(0.0, 700 - abs(13 - h) * 90))
        for h in range(0, 19)
    ]
    now = datetime(2026, 6, 25, 22, 0)
    nxt = next_drying_window(day1 + day2, now)
    assert nxt is not None
    assert "明日" in nxt["start_label"]


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

"""天気予報・降水確率 (Open-Meteo best_match)。

# データソース
Open-Meteo `forecast` API を models 未指定 (best_match = 地点ごとの最適モデル自動選択) で叩く。
key 不要・無料・商用可。気象庁モデル (jma_seamless) は降水確率を提供しない (全 None) ため、
降水確率を出す本機能では best_match を使う (日本では高解像度モデルの合議で確率込みの予報)。

- hourly: 気温・降水量・降水確率・天気コード・湿度・風 (今日明日の時間別に使う)
- daily: 天気コード・最高/最低気温・降水確率最大・日の出入り (7日週間に使う)

1 時間キャッシュ。気圧・大気質 (weather.py) とは責務を分けてこのモジュールに置く。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_CACHE_TTL_S = 60 * 60  # 1h
_cache: dict[str, tuple[float, Any]] = {}

_JST = ZoneInfo("Asia/Tokyo")

# WMO weathercode → (日本語ラベル, アイコンキー)。アイコンキーはフロントの lucide にマップ。
_CODE_MAP: dict[int, tuple[str, str]] = {
    0: ("快晴", "sun"),
    1: ("晴れ", "sun"),
    2: ("薄曇り", "cloud-sun"),
    3: ("曇り", "cloud"),
    45: ("霧", "fog"),
    48: ("霧(着氷)", "fog"),
    51: ("弱い霧雨", "drizzle"),
    53: ("霧雨", "drizzle"),
    55: ("強い霧雨", "drizzle"),
    56: ("着氷性の霧雨", "drizzle"),
    57: ("着氷性の霧雨", "drizzle"),
    61: ("弱い雨", "rain"),
    63: ("雨", "rain"),
    65: ("強い雨", "rain"),
    66: ("着氷性の雨", "rain"),
    67: ("着氷性の雨", "rain"),
    71: ("弱い雪", "snow"),
    73: ("雪", "snow"),
    75: ("強い雪", "snow"),
    77: ("霧雪", "snow"),
    80: ("にわか雨", "rain"),
    81: ("にわか雨", "rain"),
    82: ("激しいにわか雨", "rain"),
    85: ("にわか雪", "snow"),
    86: ("にわか雪", "snow"),
    95: ("雷雨", "storm"),
    96: ("雷雨(雹)", "storm"),
    99: ("雷雨(雹)", "storm"),
}


def weather_code_to_label(code: int | None) -> tuple[str, str]:
    """WMO weathercode を日本語ラベルとアイコンキーに変換する。不明は ('不明','unknown')。"""
    if code is None:
        return ("不明", "unknown")
    return _CODE_MAP.get(int(code), ("不明", "unknown"))


def laundry_hint(prob_max: float | None, precip_total: float | None) -> tuple[str, str]:
    """日中の降水確率最大・降水量から「洗濯を干していいか」を3段で返す。

    本格的な洗濯指数 (湿度・日照・風) は次フェーズ。ここは降水だけの素朴な目安。
    """
    if prob_max is None:
        return ("unknown", "降水データなし")
    precip = precip_total or 0.0
    if prob_max >= 60 or precip >= 1.0:
        return ("no", "今日は雨の見込み。部屋干しが安心")
    if prob_max >= 30 or precip >= 0.3:
        return ("caution", "にわか雨に注意。短時間なら外干しも可")
    return ("ok", "よく乾きそう。外干しOK")


def _safe_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _shape_forecast(raw: dict[str, Any], now_jst: datetime) -> dict[str, Any]:
    """Open-Meteo 生 JSON を {summary, hourly[], daily[]} に整形する。"""
    h = raw.get("hourly") or {}
    times = h.get("time", [])
    temps = h.get("temperature_2m", [])
    precs = h.get("precipitation", [])
    probs = h.get("precipitation_probability", [])
    codes = h.get("weathercode", [])
    hums = h.get("relative_humidity_2m", [])
    winds = h.get("wind_speed_10m", [])

    def _g(arr: list, i: int) -> Any:
        return arr[i] if i < len(arr) else None

    hourly: list[dict[str, Any]] = []
    for i, t in enumerate(times):
        dt = _safe_dt(t)
        if dt is None or dt < now_jst:  # 過去の時間は出さない
            continue
        if len(hourly) >= 48:  # 今日明日 (最大48h) まで
            break
        code = _g(codes, i)
        label, icon = weather_code_to_label(code)
        hourly.append({
            "time": t,
            "temp": _g(temps, i),
            "precip": _g(precs, i),
            "precip_prob": _g(probs, i),
            "code": code,
            "label": label,
            "icon": icon,
            "humidity": _g(hums, i),
            "wind": _g(winds, i),
        })

    d = raw.get("daily") or {}
    dtimes = d.get("time", [])
    dcodes = d.get("weathercode", [])
    dmax = d.get("temperature_2m_max", [])
    dmin = d.get("temperature_2m_min", [])
    dprob = d.get("precipitation_probability_max", [])
    daily: list[dict[str, Any]] = []
    for i, dte in enumerate(dtimes):
        code = _g(dcodes, i)
        label, icon = weather_code_to_label(code)
        daily.append({
            "date": dte,
            "code": code,
            "label": label,
            "icon": icon,
            "t_max": _g(dmax, i),
            "t_min": _g(dmin, i),
            "precip_prob_max": _g(dprob, i),
        })

    # 今日の日中 (9-18時) の降水確率最大・降水量で洗濯判定。日中の hourly が無ければ
    # 当日の daily 降水確率最大でフォールバックする。
    today = now_jst.date()
    day_probs: list[float] = []
    day_precs: list[float] = []
    for i, t in enumerate(times):
        dt = _safe_dt(t)
        if dt is None or dt.date() != today or not (9 <= dt.hour <= 18):
            continue
        if _g(probs, i) is not None:
            day_probs.append(probs[i])
        if _g(precs, i) is not None:
            day_precs.append(precs[i])
    if day_probs:
        prob_max: float | None = max(day_probs)
        precip_total: float | None = sum(day_precs)
    elif daily:
        prob_max = daily[0]["precip_prob_max"]
        precip_total = 0.0
    else:
        prob_max = None
        precip_total = None
    lvl, txt = laundry_hint(prob_max, precip_total)

    summary: dict[str, Any] | None = None
    if daily:
        d0 = daily[0]
        summary = {
            "code": d0["code"],
            "label": d0["label"],
            "icon": d0["icon"],
            "t_max": d0["t_max"],
            "t_min": d0["t_min"],
            "precip_prob_max": d0["precip_prob_max"],
            "laundry": {"level": lvl, "text": txt},
        }

    return {"summary": summary, "hourly": hourly, "daily": daily}


def _fetch(lat: float, lon: float) -> dict[str, Any] | None:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": (
            "temperature_2m,precipitation,precipitation_probability,"
            "weathercode,relative_humidity_2m,wind_speed_10m"
        ),
        "daily": (
            "weathercode,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,sunrise,sunset"
        ),
        "timezone": "Asia/Tokyo",
        "forecast_days": 7,
    }
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("weather_forecast_fetch_failed", error=str(exc))
        return None


def _now_jst() -> datetime:
    return datetime.now(_JST).replace(tzinfo=None)


def get_weather_forecast(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    now_jst: datetime | None = None,
) -> dict[str, Any] | None:
    """整形済みの天気予報 {summary, hourly[], daily[]} を返す。失敗時は None。"""
    s = get_settings()
    lat = latitude if latitude is not None else s.weather_latitude
    lon = longitude if longitude is not None else s.weather_longitude
    key = f"{lat:.4f}_{lon:.4f}"

    mono = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and mono - cached[0] < _CACHE_TTL_S:
        raw = cached[1]
    else:
        raw = _fetch(lat, lon)
        if raw is not None:
            _cache[key] = (mono, raw)
    if raw is None:
        return None
    return _shape_forecast(raw, now_jst or _now_jst())

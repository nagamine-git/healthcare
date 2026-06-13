"""Open-Meteo から海面気圧 (pressure_msl) を取得し、片頭痛トリガー指標を計算する。

# データソース
- API: https://api.open-meteo.com/v1/forecast (key 不要、無料、商用可)
- 取得項目: hourly pressure_msl (海面更正気圧 hPa)、温度・湿度も将来拡張用に
- past_days=2 / forecast_days=2 で「過去 48h + 未来 48h」を 1 リクエストで取得

# 医学的根拠
片頭痛と気圧の関係:
- 急激な低気圧降下で trigemenovascular activation が起きやすい (Hoffmann & Recober 2013)
- メタ解析: 前 24h で 6-10 hPa の低下で発症リスク有意 (Mukamal 2009 ほか)
- 一部の患者では「気圧変化に対する CNS の異常反応」が遺伝的に関与

# キャッシュ
1 時間キャッシュ。API は分間 1000 リクエスト無料枠で十分。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


_CACHE_TTL_S = 60 * 60  # 1h
_cache: dict[str, Any] = {}
_air_cache: dict[str, Any] = {}


@dataclass(frozen=True)
class PressurePoint:
    time_jst: str  # ISO with +09:00
    pressure_hpa: float


@dataclass(frozen=True)
class PressureSnapshot:
    current_hpa: float | None
    delta_24h_hpa: float | None  # +なら上昇、-なら降下
    delta_6h_hpa: float | None
    min_24h_hpa: float | None
    max_24h_hpa: float | None
    forecast_min_24h_hpa: float | None  # 未来 24h の最小予測
    forecast_delta_24h_hpa: float | None  # 未来 24h の変化量予測 (現在比)
    series: list[PressurePoint]  # 過去 24h + 未来 24h
    risk_level: str  # "calm" | "watch" | "warning" | "severe"
    risk_reason: str
    location_label: str


def _fetch_open_meteo(lat: float, lon: float) -> dict[str, Any] | None:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pressure_msl",
        "timezone": "Asia/Tokyo",
        "past_days": 2,
        "forecast_days": 2,
    }
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("open_meteo_fetch_failed", error=str(exc))
        return None


def get_pressure_hourly(
    *, latitude: float | None = None, longitude: float | None = None
) -> list[tuple[datetime, float]]:
    """毎時の海面更正気圧を (JST naive datetime, hPa) で返す。過去48h+未来48h。

    予報を含むので、未来数時間の気圧トレンド (片頭痛トリガー) を出せる。
    """
    settings = get_settings()
    lat = latitude if latitude is not None else settings.weather_latitude
    lon = longitude if longitude is not None else settings.weather_longitude
    data = _fetch_open_meteo(lat, lon)
    if data is None or "hourly" not in data:
        return []
    hourly = data["hourly"]
    times = hourly.get("time", [])
    pres = hourly.get("pressure_msl", [])
    out: list[tuple[datetime, float]] = []
    for t, p in zip(times, pres, strict=False):
        if p is None:
            continue
        try:
            out.append((datetime.fromisoformat(t), float(p)))
        except Exception:
            continue
    return out


def _cache_key(lat: float, lon: float) -> str:
    return f"{lat:.4f}_{lon:.4f}"


def get_pressure_snapshot(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> PressureSnapshot | None:
    """指定座標 (省略時 config) の気圧スナップショット。

    座標は小数 2 桁に丸めてキャッシュキーを生成 (~1km 精度)。
    """
    settings = get_settings()
    lat = latitude if latitude is not None else settings.weather_latitude
    lon = longitude if longitude is not None else settings.weather_longitude
    key = _cache_key(lat, lon)
    cached = _cache.get(key)
    if cached and cached["expires"] > time.time():
        return cached["value"]

    data = _fetch_open_meteo(lat, lon)
    if data is None or "hourly" not in data:
        return None

    hourly = data["hourly"]
    times_str: list[str] = hourly.get("time", [])
    pressures: list[float | None] = hourly.get("pressure_msl", [])
    if not times_str or not pressures:
        return None

    # times は "YYYY-MM-DDTHH:MM" の Asia/Tokyo aware (Open-Meteo は timezone 指定時に
    # ローカル時刻を返す。tz info 無し)
    now = datetime.now()
    # 現在に最も近い時刻の index を取る
    parsed_times = [datetime.fromisoformat(t) for t in times_str]
    idx_now = _closest_index(parsed_times, now)
    if idx_now < 0 or idx_now >= len(pressures) or pressures[idx_now] is None:
        return None

    current = float(pressures[idx_now])

    def at(target: datetime) -> float | None:
        i = _closest_index(parsed_times, target)
        if i < 0 or i >= len(pressures) or pressures[i] is None:
            return None
        return float(pressures[i])

    pres_24h_ago = at(now - timedelta(hours=24))
    pres_6h_ago = at(now - timedelta(hours=6))
    delta_24h = (current - pres_24h_ago) if pres_24h_ago is not None else None
    delta_6h = (current - pres_6h_ago) if pres_6h_ago is not None else None

    # 過去 24h の min/max
    past_window = [
        pressures[i]
        for i in range(max(0, idx_now - 24), idx_now + 1)
        if pressures[i] is not None
    ]
    min_24h = float(min(past_window)) if past_window else None
    max_24h = float(max(past_window)) if past_window else None

    # 未来 24h の予測 min と変化量
    future_window = [
        pressures[i]
        for i in range(idx_now + 1, min(len(pressures), idx_now + 25))
        if pressures[i] is not None
    ]
    fcst_min = float(min(future_window)) if future_window else None
    fcst_delta = (fcst_min - current) if fcst_min is not None else None

    # series: 過去 24h + 未来 24h (時系列順)
    series: list[PressurePoint] = []
    start = max(0, idx_now - 24)
    end = min(len(pressures), idx_now + 25)
    for i in range(start, end):
        if pressures[i] is None:
            continue
        series.append(
            PressurePoint(
                time_jst=parsed_times[i].strftime("%Y-%m-%dT%H:%M+09:00"),
                pressure_hpa=float(pressures[i]),
            )
        )

    risk_level, risk_reason = _classify_risk(
        settings.pressure_drop_warning_hpa,
        settings.pressure_drop_severe_hpa,
        delta_24h=delta_24h,
        delta_6h=delta_6h,
        forecast_delta=fcst_delta,
    )

    # 座標が config 値と異なるなら座標ラベルを使う (今後 reverse geocoding を入れるならここ)
    if (
        latitude is not None
        and longitude is not None
        and (
            abs(latitude - settings.weather_latitude) > 0.01
            or abs(longitude - settings.weather_longitude) > 0.01
        )
    ):
        label = f"位置情報 ({latitude:.3f}, {longitude:.3f})"
    else:
        label = settings.weather_location_label

    snapshot = PressureSnapshot(
        current_hpa=round(current, 1),
        delta_24h_hpa=round(delta_24h, 1) if delta_24h is not None else None,
        delta_6h_hpa=round(delta_6h, 1) if delta_6h is not None else None,
        min_24h_hpa=round(min_24h, 1) if min_24h is not None else None,
        max_24h_hpa=round(max_24h, 1) if max_24h is not None else None,
        forecast_min_24h_hpa=round(fcst_min, 1) if fcst_min is not None else None,
        forecast_delta_24h_hpa=round(fcst_delta, 1) if fcst_delta is not None else None,
        series=series,
        risk_level=risk_level,
        risk_reason=risk_reason,
        location_label=label,
    )

    _cache[key] = {"expires": time.time() + _CACHE_TTL_S, "value": snapshot}
    return snapshot


def _closest_index(times: list[datetime], target: datetime) -> int:
    if not times:
        return -1
    # 時系列昇順を仮定
    best_i = 0
    best_d = abs((times[0] - target).total_seconds())
    for i in range(1, len(times)):
        d = abs((times[i] - target).total_seconds())
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _classify_risk(
    warning_hpa: float,
    severe_hpa: float,
    *,
    delta_24h: float | None,
    delta_6h: float | None,
    forecast_delta: float | None,
) -> tuple[str, str]:
    """4 段階のリスク判定。

    severe: 過去 24h で -severe_hpa 以下、または 6h で -warning_hpa 以下の急降下
    warning: 過去 24h で -warning_hpa 以下、または未来 24h で -severe_hpa 以下の予測
    watch: 未来 24h で -warning_hpa 以下の予測
    calm: それ以外
    """
    if delta_24h is not None and delta_24h <= -severe_hpa:
        return (
            "severe",
            f"過去 24h で気圧が {delta_24h:+.1f} hPa 急降下。片頭痛発症リスク極めて高",
        )
    if delta_6h is not None and delta_6h <= -warning_hpa:
        return (
            "severe",
            f"過去 6h で気圧が {delta_6h:+.1f} hPa 急降下。片頭痛発症リスク極めて高",
        )
    if delta_24h is not None and delta_24h <= -warning_hpa:
        return (
            "warning",
            f"過去 24h で {delta_24h:+.1f} hPa 低下。片頭痛発症リスクあり",
        )
    if forecast_delta is not None and forecast_delta <= -severe_hpa:
        return (
            "warning",
            f"今後 24h で {forecast_delta:+.1f} hPa の降下予測。予防的に水分・睡眠確保",
        )
    if forecast_delta is not None and forecast_delta <= -warning_hpa:
        return (
            "watch",
            f"今後 24h で {forecast_delta:+.1f} hPa の降下予測。要注意",
        )
    return ("calm", "気圧は安定")


@dataclass(frozen=True)
class AirQualitySnapshot:
    pm2_5: float | None  # μg/m³
    pm10: float | None
    no2: float | None
    o3: float | None
    uv_index: float | None
    aqi: int | None  # US EPA AQI (0-500)
    risk_level: str  # "good" | "moderate" | "unhealthy_sensitive" | "unhealthy"
    risk_reason: str
    location_label: str


def _fetch_air_quality(lat: float, lon: float) -> dict[str, Any] | None:
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "pm2_5,pm10,nitrogen_dioxide,ozone,uv_index,us_aqi",
        "timezone": "Asia/Tokyo",
    }
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("open_meteo_air_quality_failed", error=str(exc))
        return None


def get_air_quality_snapshot(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> AirQualitySnapshot | None:
    settings = get_settings()
    lat = latitude if latitude is not None else settings.weather_latitude
    lon = longitude if longitude is not None else settings.weather_longitude
    key = _cache_key(lat, lon)
    cached = _air_cache.get(key)
    if cached and cached["expires"] > time.time():
        return cached["value"]

    data = _fetch_air_quality(lat, lon)
    if data is None or "current" not in data:
        return None
    cur = data["current"]

    pm2_5 = _safe_float(cur.get("pm2_5"))
    pm10 = _safe_float(cur.get("pm10"))
    no2 = _safe_float(cur.get("nitrogen_dioxide"))
    o3 = _safe_float(cur.get("ozone"))
    uv = _safe_float(cur.get("uv_index"))
    aqi_raw = cur.get("us_aqi")
    aqi = int(aqi_raw) if isinstance(aqi_raw, (int, float)) else None

    risk_level, risk_reason = _classify_air_risk(pm2_5=pm2_5, aqi=aqi)

    if (
        latitude is not None
        and longitude is not None
        and (
            abs(latitude - settings.weather_latitude) > 0.01
            or abs(longitude - settings.weather_longitude) > 0.01
        )
    ):
        label = f"位置情報 ({latitude:.3f}, {longitude:.3f})"
    else:
        label = settings.weather_location_label

    snap = AirQualitySnapshot(
        pm2_5=round(pm2_5, 1) if pm2_5 is not None else None,
        pm10=round(pm10, 1) if pm10 is not None else None,
        no2=round(no2, 1) if no2 is not None else None,
        o3=round(o3, 1) if o3 is not None else None,
        uv_index=round(uv, 1) if uv is not None else None,
        aqi=aqi,
        risk_level=risk_level,
        risk_reason=risk_reason,
        location_label=label,
    )
    _air_cache[key] = {"expires": time.time() + _CACHE_TTL_S, "value": snap}
    return snap


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _classify_air_risk(*, pm2_5: float | None, aqi: int | None) -> tuple[str, str]:
    """WHO 2021 ガイドライン (24h PM2.5 < 15 μg/m³) + US EPA AQI を組み合わせ。

    認知パフォーマンスへの影響 (Zhang 2018 PNAS): PM2.5 暴露 1 SD 増で言語テスト 1.13σ↓
    """
    if pm2_5 is None and aqi is None:
        return "good", "データなし"

    if (pm2_5 is not None and pm2_5 >= 55.5) or (aqi is not None and aqi >= 151):
        return (
            "unhealthy",
            f"PM2.5 {pm2_5 if pm2_5 is not None else '?'} μg/m³ / AQI {aqi if aqi is not None else '?'}。"
            "外出・換気を控え、屋外運動回避",
        )
    if (pm2_5 is not None and pm2_5 >= 35.5) or (aqi is not None and aqi >= 101):
        return (
            "unhealthy_sensitive",
            f"PM2.5 {pm2_5} μg/m³。敏感層は短時間屋外活動に留める、室内空気清浄機推奨",
        )
    if (pm2_5 is not None and pm2_5 >= 15.5) or (aqi is not None and aqi >= 51):
        return (
            "moderate",
            f"PM2.5 {pm2_5} μg/m³。長時間屋外運動は控えめ、認知タスク前は注意",
        )
    return (
        "good",
        f"PM2.5 {pm2_5 if pm2_5 is not None else '?'} μg/m³、WHO 基準内",
    )


def air_quality_to_dict(snap: AirQualitySnapshot | None) -> dict[str, Any] | None:
    if snap is None:
        return None
    return {
        "pm2_5": snap.pm2_5,
        "pm10": snap.pm10,
        "no2": snap.no2,
        "o3": snap.o3,
        "uv_index": snap.uv_index,
        "aqi": snap.aqi,
        "risk_level": snap.risk_level,
        "risk_reason": snap.risk_reason,
        "location_label": snap.location_label,
    }


def reset_cache() -> None:
    """テスト用にキャッシュを完全クリアする。"""
    _cache.clear()
    _air_cache.clear()


def to_dict(snap: PressureSnapshot | None) -> dict[str, Any] | None:
    if snap is None:
        return None
    return {
        "current_hpa": snap.current_hpa,
        "delta_24h_hpa": snap.delta_24h_hpa,
        "delta_6h_hpa": snap.delta_6h_hpa,
        "min_24h_hpa": snap.min_24h_hpa,
        "max_24h_hpa": snap.max_24h_hpa,
        "forecast_min_24h_hpa": snap.forecast_min_24h_hpa,
        "forecast_delta_24h_hpa": snap.forecast_delta_24h_hpa,
        "risk_level": snap.risk_level,
        "risk_reason": snap.risk_reason,
        "location_label": snap.location_label,
        "series": [
            {"time": p.time_jst, "hpa": p.pressure_hpa} for p in snap.series
        ],
    }

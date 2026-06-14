"""未来予測 (forecast)。確度の高い順に複数の見通しを返す。

階層 (確度):
- 【高】片頭痛リスク予報 (24-48h): 検証済み個人トリガー(気圧変動) × Open-Meteo の48h気圧予報。
- 【中】今日この先のエネルギー(Body Battery)推移: 直近の消耗スロープから枯渇時刻を外挿。
- 【低】明日の一次指標: 欠損補完エンジンを翌日に適用(決定的特徴+慣性)。ベイズ天井で参考値。

各予測に confidence(high/medium/low) を付け、UI は確度で濃淡を付ける。
気圧予報は実スキルがあり検証済みトリガーと組むため濃い。明日のHRV等は薄い。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.integrations.weather import get_pressure_hourly
from app.models import BodyBattery
from app.scoring.migraine_triggers import WINDOW_H, _exposure_pressure_drop, analyze_triggers
from app.scoring.timewindow import JST, app_today


def _now_jst() -> datetime:
    return datetime.now(JST).replace(tzinfo=None)


def _rel_label(d_offset: int) -> str:
    return {0: "今日", 1: "明日", 2: "明後日"}.get(d_offset, "")


def _migraine_forecast(now_jst: datetime) -> dict[str, Any] | None:
    """48h先までの片頭痛リスク予報 (12h バケット)。"""
    series = get_pressure_hourly()  # JST naive, 過去48h+未来48h
    if not series:
        return None
    tr = analyze_triggers(app_today())
    pf = next((f for f in tr.get("factors", []) if f["key"] == "pressure_drop"), None)

    # 個人閾値を使うのは「気圧変動が大きいほど頭痛 (誘発方向)」が検証できた時だけ。
    # 方向が逆(抑制?)や未確立なら、誤って高リスクを出さず一般医学基準+低確度にする。
    personal = pf is not None and pf.get("direction") == "誘発"
    if personal:
        conf = {"strong": "high", "suggestive": "medium"}.get(pf["tier"], "low")
        case_mean = pf.get("case_mean")
        control_mean = pf.get("control_mean")
    else:
        conf = "low"
        case_mean = control_mean = None

    def classify(swing: float) -> str:
        if case_mean is not None and control_mean is not None:
            mid = (case_mean + control_mean) / 2
            if swing >= case_mean:
                return "high"
            return "elevated" if swing >= mid else "low"
        # 検証前のフォールバック (一般に 24h で 8hPa 超の変動は要注意)
        return "high" if swing >= 8 else ("elevated" if swing >= 5 else "low")

    buckets: list[dict[str, Any]] = []
    for b in range(4):  # 12h × 4 = 48h
        bstart = now_jst + timedelta(hours=b * 12)
        bend = bstart + timedelta(hours=12)
        swings: list[float] = []
        h = bstart
        while h < bend:
            w = _exposure_pressure_drop(series, h - timedelta(hours=WINDOW_H), h)
            if w is not None:
                swings.append(w)
            h += timedelta(hours=3)
        if not swings:
            continue
        swing = max(swings)
        d_off = (bstart.date() - now_jst.date()).days
        part = "午前" if bstart.hour < 12 else ("午後" if bstart.hour < 18 else "夜")
        buckets.append({
            "label": f"{_rel_label(d_off)}{part}",
            "start": bstart.isoformat(timespec="hours"),
            "swing_hpa": round(swing, 1),
            "risk": classify(swing),
        })
    if not buckets:
        return None
    rank = {"high": 2, "elevated": 1, "low": 0}
    peak = max(buckets, key=lambda x: rank[x["risk"]])
    return {
        "confidence": conf,
        "reliability": tr.get("reliability"),
        "buckets": buckets,
        "peak": peak,
        "is_trigger_validated": personal,
    }


def _energy_today(now_jst: datetime) -> dict[str, Any] | None:
    """直近の Body Battery スロープから、残りの一日の推移と枯渇時刻を外挿。"""
    now_utc = now_jst - timedelta(hours=9)
    with session_scope() as s:
        rows = s.execute(
            select(BodyBattery.ts, BodyBattery.value)
            .where(BodyBattery.ts >= now_utc - timedelta(hours=4), BodyBattery.ts <= now_utc)
            .order_by(BodyBattery.ts)
        ).all()
    pts = [(ts, float(v)) for ts, v in rows if v is not None]
    if len(pts) < 3:
        return None
    # 時間(h) を x とした最小二乗の傾き
    t0 = pts[0][0]
    xs = [(ts - t0).total_seconds() / 3600 for ts, _ in pts]
    ys = [v for _, v in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denom  # /h
    current = ys[-1]
    eta = None
    floor = 20.0
    if slope < -0.5 and current > floor:
        hours_to_floor = (current - floor) / (-slope)
        if hours_to_floor < 18:
            eta = (now_jst + timedelta(hours=hours_to_floor)).isoformat(timespec="minutes")
    return {
        "confidence": "medium",
        "current": round(current),
        "slope_per_h": round(slope, 1),
        "empty_eta": eta,
        "floor": int(floor),
    }


def _tomorrow_metrics() -> dict[str, Any]:
    """翌日の一次指標を補完エンジンで予測 (決定的特徴+慣性)。ベイズ天井で低確度。"""
    from app.scoring.imputation import impute_day
    return impute_day(app_today() + timedelta(days=1), only_missing=True)


def forecast(*, now_jst: datetime | None = None) -> dict[str, Any]:
    now_jst = now_jst or _now_jst()
    return {
        "generated_at": now_jst.isoformat(timespec="minutes"),
        "location": "Tokyo",
        "migraine": _migraine_forecast(now_jst),
        "energy_today": _energy_today(now_jst),
        "tomorrow": _tomorrow_metrics(),
    }

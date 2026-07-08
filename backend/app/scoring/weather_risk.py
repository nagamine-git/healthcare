"""屋外運動の天気リスク (熱中症・降水) — 決定論的な純関数。

WBGT は黒球温度が無いため近似: Stull(2011) の湿球温度 Tw を気温+相対湿度から推定し、
屋内式 WBGT ≈ 0.7*Tw + 0.3*Ta を使う (日射項なし、屋外晴天ではやや過小評価 → レベル閾値は
環境省の運動指針に合わせ保守的に読む)。
"""

from __future__ import annotations

import math
from typing import Any


def wet_bulb_stull(temp_c: float, rh_pct: float) -> float:
    """Stull (2011) 近似の湿球温度。"""
    t, rh = temp_c, max(1.0, min(100.0, rh_pct))
    return (
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh) - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def wbgt_approx(temp_c: float, rh_pct: float) -> float:
    return 0.7 * wet_bulb_stull(temp_c, rh_pct) + 0.3 * temp_c


def heat_level(wbgt: float) -> str:
    """環境省の運動指針区分。"""
    if wbgt < 21:
        return "安全"
    if wbgt < 25:
        return "注意"
    if wbgt < 28:
        return "警戒"
    if wbgt < 31:
        return "厳重警戒"
    return "危険"


def brief_from_hourly(hourly: list[dict[str, Any]], hours: int = 18) -> dict[str, Any]:
    """weather_forecast の hourly を屋外運動判断用に要約する。

    hourly の想定キー: time (ISO, JST), temp_c or temperature, precip_prob, humidity。
    キー名の揺れに防御的に対応する。
    """
    rows: list[dict[str, Any]] = []
    for h in hourly[:hours]:
        t = h.get("temp_c", h.get("temperature", h.get("temp")))
        rh = h.get("humidity", h.get("rh"))
        pp = h.get("precip_prob", h.get("precipitation_probability"))
        time_s = str(h.get("time", ""))[11:16]  # HH:MM
        level = heat_level(wbgt_approx(float(t), float(rh))) if t is not None and rh is not None else None
        rows.append({
            "time": time_s, "temp_c": t, "precip_prob": pp, "heat": level,
        })
    rainy = [r["time"] for r in rows if (r["precip_prob"] or 0) >= 50]
    hot = [r["time"] for r in rows if r["heat"] in ("厳重警戒", "危険")]
    ok = [
        r["time"] for r in rows
        if (r["precip_prob"] or 0) < 30 and r["heat"] in ("安全", "注意", None)
    ]
    return {
        "hours": rows,
        "rain_risk_times": rainy[:8],
        "heat_caution_times": hot[:8],
        "good_outdoor_times": ok[:8],
    }

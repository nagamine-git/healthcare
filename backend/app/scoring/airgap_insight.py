"""Airgap (スマホデトックス) の浪費実測と睡眠/HRVの自己内相関を検出する。

n=1 の自己内比較 (between-subject ではなく within-subject)。高浪費日/低浪費日を
分位で二分し、各群の睡眠・HRVサブスコア平均を比べる。相関であり因果ではない、
サンプルも小さいことを前提に、あくまで「気づきのきっかけ」として保守的に扱う。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

# 各群 (高浪費/低浪費) に最低これだけの日数が無ければ「データ不足」とする。
MIN_DAYS_PER_GROUP = 5


def _avg(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def compute_airgap_sleep_insight(
    rows: list[dict[str, Any]], min_days_per_group: int = MIN_DAYS_PER_GROUP
) -> dict[str, Any]:
    """rows: [{"waste_min": int, "sleep_sub": float|None, "hrv_sub": float|None}, ...]

    waste_min の順位で上位半分/下位半分に分け (中央値タイの偏りを避けるため値でなく
    順位で分割)、各群の sleep_sub/hrv_sub 平均を比較する。日数が奇数なら中央の1日は
    どちらの群にも含めない (群のバランスを保つ)。
    """
    measured = [r for r in rows if r.get("waste_min") is not None]
    n = len(measured)
    half = n // 2
    if half < min_days_per_group:
        return {"available": False, "days_analyzed": n,
                "days_needed_per_group": min_days_per_group}

    ordered = sorted(measured, key=lambda r: r["waste_min"])
    low = ordered[:half]
    high = ordered[-half:]

    sleep_low, sleep_high = _avg(low, "sleep_sub"), _avg(high, "sleep_sub")
    hrv_low, hrv_high = _avg(low, "hrv_sub"), _avg(high, "hrv_sub")

    return {
        "available": True,
        "days_analyzed": n,
        "days_per_group": half,
        "low_waste_avg_min": round(sum(r["waste_min"] for r in low) / half, 1),
        "high_waste_avg_min": round(sum(r["waste_min"] for r in high) / half, 1),
        "sleep_low": sleep_low,
        "sleep_high": sleep_high,
        "sleep_diff": (round(sleep_high - sleep_low, 1)
                       if sleep_low is not None and sleep_high is not None else None),
        "hrv_low": hrv_low,
        "hrv_high": hrv_high,
        "hrv_diff": (round(hrv_high - hrv_low, 1)
                     if hrv_low is not None and hrv_high is not None else None),
    }


def gather_airgap_sleep_rows(session: Session, today, days: int = 90) -> list[dict[str, Any]]:
    """直近 days 日の AirgapDaily × DailyScore (同日) を突き合わせて行にする。"""
    from app.models import AirgapDaily, DailyScore

    since = today - timedelta(days=days)
    result = session.execute(
        select(AirgapDaily.waste_min, DailyScore.sleep_sub, DailyScore.hrv_sub)
        .join(DailyScore, DailyScore.date == AirgapDaily.date)
        .where(AirgapDaily.date >= since, AirgapDaily.date <= today)
    ).all()
    return [{"waste_min": w, "sleep_sub": s, "hrv_sub": h} for w, s, h in result]

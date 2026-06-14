"""統一予測バックボーン: 任意指標 × 任意期間で 実測/推定/予報 を一括返す。

過去・現在・未来を1つの系列に統合する単一の真実:
- actual   : 実測値がある日 (区間なし)
- imputed  : 過去〜当日で実測が欠けた日 → 補完エンジンで推定 (区間+確度)
- forecast : 未来日 → 同じ補完エンジンを未来日に適用 (決定的特徴+慣性、低確度)
- none     : 候補が無く推定もできない日

全 UI はこの 1 エンドポイントを食えば、過去欠損も未来も同じ「値+範囲+確度」で
一貫表示できる。確度→濃淡、low/high→範囲バンド。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from typing import Any

from app.scoring import imputation as imp
from app.scoring.timewindow import app_today

# 指標の単位 (UI 表示用)
_UNIT: dict[str, str] = {
    "sleep_score": "", "sleep_total_min": "分", "hrv": "ms",
    "body_battery": "", "resting_hr": "bpm", "steps": "歩",
}


def predict_series(
    metric: str, start: date_type, end: date_type, *, today: date_type | None = None
) -> dict[str, Any]:
    """metric を [start, end] の各日について 実測/推定/予報 で埋めた系列を返す。"""
    if metric not in imp.METRICS:
        raise ValueError(f"unknown metric: {metric}")
    today = today or app_today()
    # 範囲全体 + 学習用に過去 _HISTORY_DAYS 日を 1 回で読む
    hist = imp._load_history(end, history_start=start - timedelta(days=imp._HISTORY_DAYS))
    tgts = hist["tgts"]

    points: list[dict[str, Any]] = []
    d = start
    while d <= end:
        actual = tgts.get(d, {}).get(metric)
        if actual is not None:
            points.append({
                "date": d.isoformat(), "value": round(actual, 1), "kind": "actual",
                "confidence": None, "low": None, "high": None, "drivers": [],
            })
        else:
            res = imp.impute_metric(metric, d, hist)
            kind = "forecast" if d > today else "imputed"
            if res is None:
                points.append({
                    "date": d.isoformat(), "value": None, "kind": "none",
                    "confidence": None, "low": None, "high": None, "drivers": [],
                })
            else:
                # 未来は外挿で不確実 → 確度を 1 段下げる (high→medium 等)
                conf = res.confidence
                if kind == "forecast":
                    conf = {"high": "medium", "medium": "low", "low": "low"}[conf]
                points.append({
                    "date": d.isoformat(), "value": round(res.value, 1), "kind": kind,
                    "confidence": conf, "low": res.low, "high": res.high,
                    "drivers": res.drivers,
                })
        d += timedelta(days=1)

    return {
        "metric": metric, "unit": _UNIT.get(metric, ""),
        "start": start.isoformat(), "end": end.isoformat(), "today": today.isoformat(),
        "points": points,
    }

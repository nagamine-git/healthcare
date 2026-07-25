"""VO2Max の推定 (Garmin が計算できない時のフォールバック。参考値)。

Garmin のランニング VO2Max は GPS ペースが必須で、未捕捉のランでは欠測する
(実例: 2026-07-04 の 21:00 ラン、距離26mしか記録されず計測不能)。そこで公表式で幅つき推定する:

1. Uth–Sørensen–Overgaard–Pedersen (2004): VO2Max ≈ 15.3 × HRmax / HRrest。
   安静時心拍と最大心拍だけで出せる (走らない日でも可)。検証誤差 ±5 前後。
2. ACSM ランニング式 + Swain の %HRR≈%VO2Max 外挿:
   サブマックス走の VO2 = 3.5 + 0.2×速度(m/分) を、心拍予備率で最大まで外挿。
   速度は GPS 距離が信頼できればそれを、無ければ 歩数×ストライド で代替。

2法の範囲 [low, high] と中点を返す。**医療・トレーニング処方の根拠にしない参考値**。

`estimate_for_workout()` は DB (安静時心拍・実測最大心拍) を引いて上記を組み立てる版で、
ingest/garmin_sync.py がラン系ワークアウトの同期ごとに metric_sample
(source="estimate", metric_key="vo2max_estimated") へ永続化し、
api/body_distribution.py が Garmin 実測 VO2max 欠測時のフォールバックとして参照する。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailySummary, Workout

# GPS 距離がこの割合以上 歩数×ストライド推定と乖離していたら GPS 不良とみなす
_MIN_VALID_DISTANCE_M = 500.0
_MIN_SPEED_M_MIN = 80.0    # 歩行未満は外挿式の適用外
_MIN_HRR_FRAC = 0.5        # %HRR 50% 未満の楽な運動からの外挿は誤差が大きすぎる
# Garmin の走行系アクティビティタイプ。この推定式はランのみ対象 (歩数/ストライドで速度化する前提)
RUN_TYPES = ("running", "treadmill_running", "trail_running")


def uth_estimate(hr_max: float, hr_rest: float) -> float | None:
    """Uth (2004): 15.3 × HRmax/HRrest。"""
    if hr_max <= 0 or hr_rest <= 0 or hr_max <= hr_rest:
        return None
    return round(15.3 * hr_max / hr_rest, 1)


def acsm_submax_estimate(
    *, speed_m_min: float, avg_hr: float, hr_rest: float, hr_max: float
) -> float | None:
    """ACSM ラン式の VO2 を %HRR (Swain) で VO2Max へ外挿。"""
    if speed_m_min < _MIN_SPEED_M_MIN or hr_max <= hr_rest:
        return None
    hrr_frac = (avg_hr - hr_rest) / (hr_max - hr_rest)
    if hrr_frac < _MIN_HRR_FRAC or hrr_frac > 1.0:
        return None
    vo2_submax = 3.5 + 0.2 * speed_m_min
    return round(vo2_submax / hrr_frac, 1)


def estimate_for_run(
    *,
    duration_s: float | None,
    avg_hr: float | None,
    hr_rest: float | None,
    hr_max: float | None,
    distance_m: float | None = None,
    steps: float | None = None,
    stride_m: float | None = None,
) -> dict[str, Any] | None:
    """1本のランから幅つき推定を組み立てる。材料不足なら None。"""
    if not hr_rest or not hr_max or hr_max <= hr_rest:
        return None
    values: dict[str, float] = {}
    u = uth_estimate(hr_max, hr_rest)
    if u is not None:
        values["uth"] = u

    speed_src: str | None = None
    speed_m_min: float | None = None
    if duration_s and duration_s >= 300:
        if distance_m and distance_m >= _MIN_VALID_DISTANCE_M:
            speed_m_min = distance_m / (duration_s / 60)
            speed_src = "gps"
        elif steps and stride_m:
            # GPS 欠測 → 加速度計の歩数×ストライドで距離を代替 (精度は落ちる)
            speed_m_min = steps * stride_m / (duration_s / 60)
            speed_src = "steps"
    if speed_m_min is not None and avg_hr:
        a = acsm_submax_estimate(
            speed_m_min=speed_m_min, avg_hr=avg_hr, hr_rest=hr_rest, hr_max=hr_max
        )
        if a is not None:
            values["acsm_submax"] = a

    if not values:
        return None
    lo, hi = min(values.values()), max(values.values())
    return {
        "mid": round((lo + hi) / 2, 1),
        "low": lo,
        "high": hi,
        "methods": values,
        "speed_source": speed_src,
        "note": "参考値 (公表式による推定。Garmin実測とは別物)",
    }


def resting_hr_near(session: Session, on_date: date_type) -> float | None:
    """指定日以前の直近の安静時心拍 (DailySummary.resting_hr)。"""
    row = session.execute(
        select(DailySummary.resting_hr)
        .where(DailySummary.date <= on_date, DailySummary.resting_hr.isnot(None))
        .order_by(DailySummary.date.desc())
        .limit(1)
    ).scalar()
    return float(row) if row is not None else None


def hr_max_observed(session: Session) -> float | None:
    """直近90日の実測最大心拍 (HRmax の下限推定として使う)。"""
    row = session.execute(
        select(Workout.max_hr)
        .where(Workout.max_hr.isnot(None), Workout.start >= datetime.utcnow() - timedelta(days=90))
        .order_by(Workout.max_hr.desc())
        .limit(1)
    ).scalar()
    return float(row) if row is not None else None


def estimate_for_workout(
    session: Session,
    *,
    workout_type: str | None,
    start: datetime,
    duration_s: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    distance_m: float | None,
    raw_json: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """1本のワークアウト (ラン系のみ) から DB 参照込みで幅つき VO2Max 推定を組み立てる。

    workout_review API のオンデマンド表示と garmin_sync の永続化の両方から呼ばれる
    共通実装 (安静時心拍・実測最大心拍の取り方を1箇所に集約)。
    """
    if workout_type not in RUN_TYPES:
        return None
    raw = raw_json or {}
    hr_max = hr_max_observed(session) or (max_hr if max_hr else None)
    stride_cm = raw.get("avgStrideLength")
    jst_date = (start + timedelta(hours=9)).date()
    return estimate_for_run(
        duration_s=float(duration_s or 0),
        avg_hr=avg_hr,
        hr_rest=resting_hr_near(session, jst_date),
        hr_max=hr_max,
        distance_m=distance_m,
        steps=raw.get("steps"),
        stride_m=float(stride_cm) / 100 if stride_cm else None,
    )

"""体重・体脂肪率の時間加重指数平滑 (測定ノイズ除去)。

家庭用の測定値は水分・グリコーゲン (炭水化物1g→水3-4g)・食事・塩分・発汗・ホルモンで
日々 ±1-2kg、体脂肪率 (生体インピーダンス) は ±2-4% 揺れる = ノイズ。一方で本当に
知りたい脂肪量・筋量はゆっくり (週0.1-0.5kg) しか動かない = 信号。

そこで「経過日数で指数減衰させた加重平均」でトレンド (真値の推定) を抽出する:

    weight_i = 2 ** (-Δdays_i / half_life)   (最新の測定からの経過日数)

測定間隔が不定期でも時間で重み付けするので数学的に正しい (測定の「順番」ではなく
「いつ測ったか」で効く)。生値 (直近1回) も併せて返す (表示用に残す)。
明らかな誤測 (中央値から outlier_kg 以上外れる) は除外して頑健性も確保する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as date_type

from sqlalchemy import select

from app.db import session_scope
from app.models import WeightSample
from app.scoring.timewindow import JST


@dataclass(frozen=True)
class BodyEstimate:
    weight_kg: float | None  # 平滑トレンド
    body_fat_pct: float | None  # 平滑トレンド
    muscle_kg: float | None  # 平滑トレンド
    raw_weight_kg: float | None  # 直近1回 (生値)
    raw_body_fat_pct: float | None
    raw_ts: datetime | None
    n: int  # 平滑に使った測定数


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2


def _wavg(samples: list[tuple[float, float]]) -> float | None:
    sw = sum(w for _, w in samples)
    if sw <= 0:
        return None
    return sum(v * w for v, w in samples) / sw


def smoothed_body(
    target: date_type | None = None,
    *,
    half_life_days: float = 14.0,
    window_days: int = 60,
    outlier_kg: float = 8.0,
    outlier_bf_pct: float = 10.0,
    outlier_muscle_kg: float = 8.0,
) -> BodyEstimate:
    """直近 window_days の体組成を時間加重指数平滑したトレンドを返す。"""
    if target is not None:
        end = datetime.combine(target, datetime.max.time())
    else:
        end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=window_days)

    with session_scope() as session:
        rows = session.execute(
            select(
                WeightSample.ts, WeightSample.weight_kg,
                WeightSample.body_fat_pct, WeightSample.muscle_kg,
            )
            .where(WeightSample.ts >= start, WeightSample.ts <= end)
            .order_by(WeightSample.ts.desc())
        ).all()

    if not rows:
        return BodyEstimate(None, None, None, None, None, None, 0)

    ref_ts, raw_w, raw_bf, _raw_m = rows[0]
    # 誤測ガード: 各指標の中央値から大きく外れる値は除外。体重だけでなく
    # 体脂肪率・筋量も BIA の測定誤差 (体脂肪率は ±2-4% 揺れる) で外れ値が出るため、
    # 体重が正常な行でも bf/筋量が極端ならその値だけ平均から外す。
    med_w = _median([float(r[1]) for r in rows])
    _bf_vals = [float(r[2]) for r in rows if r[2] is not None]
    _m_vals = [float(r[3]) for r in rows if r[3] is not None]
    med_bf = _median(_bf_vals) if _bf_vals else None
    med_m = _median(_m_vals) if _m_vals else None

    def decay(ts: datetime) -> float:
        days = (ref_ts - ts).total_seconds() / 86400.0
        return 2.0 ** (-days / half_life_days)

    wsamp: list[tuple[float, float]] = []
    bfsamp: list[tuple[float, float]] = []
    msamp: list[tuple[float, float]] = []
    for ts, w, bf, m in rows:
        if w is None or abs(float(w) - med_w) > outlier_kg:
            continue
        wt = decay(ts)
        wsamp.append((float(w), wt))
        if bf is not None and (med_bf is None or abs(float(bf) - med_bf) <= outlier_bf_pct):
            bfsamp.append((float(bf), wt))
        if m is not None and (med_m is None or abs(float(m) - med_m) <= outlier_muscle_kg):
            msamp.append((float(m), wt))

    return BodyEstimate(
        weight_kg=_wavg(wsamp),
        body_fat_pct=_wavg(bfsamp),
        muscle_kg=_wavg(msamp),
        raw_weight_kg=float(raw_w) if raw_w is not None else None,
        raw_body_fat_pct=float(raw_bf) if raw_bf is not None else None,
        raw_ts=ref_ts.replace(tzinfo=UTC).astimezone(JST).replace(tzinfo=None) if ref_ts else None,
        n=len(wsamp),
    )

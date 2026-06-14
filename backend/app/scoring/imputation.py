"""欠損した一次健康指標の統計的補完 (imputation)。

ウォッチ未装着などで当日の一次データ (睡眠/HRV/Body Battery/安静時心拍/歩数) が
欠けているとき、ウォッチ無しでも揃う手がかり + 本人の過去データから推定する。

手法: 個人履歴ベースの k 近傍 (kNN) 回帰 + 生理学的事前知識。
- 特徴量 (ウォッチ不要): 曜日/季節/月相, 気圧(水準・24h変化), 前夜の飲酒, 前日カフェイン,
  主観チェックイン(あれば), そして直近に実測できていた同指標の「慣性」。
- 標準化した特徴空間で当日に似た過去日を探し、ガウスカーネルで加重平均。
  近傍のばらつき = 予測区間 = 信頼度。近傍が乏しければ個人ローリング中央値にフォールバック。
- 完璧は装わない: すべての推定に confidence(high/medium/low) と区間、寄与要因を付ける。

設計判断: n が小さい個人時系列では全結合 ML は過学習する。kNN は非線形・解釈可能・
小標本で素直に劣化する。生理学的に効く特徴 (飲酒→HRV低下, 気圧低下→不調) を重み付けで効かせる。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import (
    AlcoholIntake,
    BodyBatteryDaily,
    CaffeineIntake,
    DailySummary,
    HrvDaily,
    MetricSample,
    SleepSession,
    SubjectiveCheckin,
)
from app.scoring.timewindow import app_today

# 補完対象の指標と妥当な値域 (クランプ用)。
METRICS: dict[str, tuple[float, float]] = {
    "sleep_score": (1.0, 100.0),
    "sleep_total_min": (120.0, 660.0),
    "hrv": (10.0, 150.0),
    "body_battery": (5.0, 100.0),
    "resting_hr": (35.0, 90.0),
    "steps": (0.0, 30000.0),
}

# 特徴量の重み (生理学的事前知識)。慣性=直近の本人水準が最強の予測子。
_FEATURE_WEIGHTS: dict[str, float] = {
    "inertia": 2.2,
    "alcohol_prev": 1.5,
    "pressure_change": 1.2,
    "subj_energy": 1.2,
    "subj_stress": 1.2,
    "subj_soreness": 1.0,
    "subj_mood": 0.8,
    "pressure_mean": 0.8,
    "caffeine_prev": 0.8,
    "weekend": 1.0,
    "dow_sin": 0.6,
    "dow_cos": 0.6,
    "month_sin": 0.4,
    "month_cos": 0.4,
    "moon": 0.4,
}

_HISTORY_DAYS = 180
_K = 12          # 近傍数の上限
_MIN_NEIGHBORS = 3  # これ未満は baseline へフォールバック
_FAR_Z = 2.6     # クエリが全近傍からこれ以上離れていれば外挿として信頼度を下げる


@dataclass
class Imputed:
    metric: str
    value: float
    confidence: str          # high | medium | low
    method: str              # knn | baseline
    low: float | None
    high: float | None
    n_eff: float
    drivers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric, "value": round(self.value, 1),
            "confidence": self.confidence, "method": self.method,
            "low": round(self.low, 1) if self.low is not None else None,
            "high": round(self.high, 1) if self.high is not None else None,
            "n_eff": round(self.n_eff, 1), "drivers": self.drivers,
        }


def _moon_illumination(d: date_type) -> float:
    """月の輝面比 0..1 (0=新月, 1=満月)。基準新月 2000-01-06。"""
    ref = date_type(2000, 1, 6)
    phase = ((d - ref).days % 29.530588853) / 29.530588853
    return (1 - math.cos(2 * math.pi * phase)) / 2


def _jst_date(ts) -> date_type:
    return (ts + timedelta(hours=9)).date()


def _load_history(target: date_type) -> dict[str, Any]:
    """過去 _HISTORY_DAYS 日 + target の特徴量・指標を JST 日単位で集約して返す。"""
    start = target - timedelta(days=_HISTORY_DAYS)
    # ts ベースのテーブルは JST 日付に丸めるため UTC 窓を少し広めに取る
    ts_lo = (start - timedelta(days=1))
    from datetime import datetime as _dt
    ts_lo_dt = _dt.combine(ts_lo, _dt.min.time())
    ts_hi_dt = _dt.combine(target + timedelta(days=1), _dt.min.time())

    feats: dict[date_type, dict[str, float]] = {}
    tgts: dict[date_type, dict[str, float]] = {}

    def _f(d: date_type) -> dict[str, float]:
        return feats.setdefault(d, {})

    with session_scope() as s:
        for row in s.execute(
            select(SleepSession).where(SleepSession.date >= start, SleepSession.date <= target)
        ).scalars():
            t = tgts.setdefault(row.date, {})
            if row.sleep_score is not None:
                t["sleep_score"] = float(row.sleep_score)
            if row.total_min is not None:
                t["sleep_total_min"] = float(row.total_min)
        for row in s.execute(
            select(HrvDaily).where(HrvDaily.date >= start, HrvDaily.date <= target)
        ).scalars():
            if row.last_night_avg is not None:
                tgts.setdefault(row.date, {})["hrv"] = float(row.last_night_avg)
        for row in s.execute(
            select(BodyBatteryDaily).where(BodyBatteryDaily.date >= start, BodyBatteryDaily.date <= target)
        ).scalars():
            if row.morning_value is not None:
                tgts.setdefault(row.date, {})["body_battery"] = float(row.morning_value)
        for row in s.execute(
            select(DailySummary).where(DailySummary.date >= start, DailySummary.date <= target)
        ).scalars():
            t = tgts.setdefault(row.date, {})
            if row.resting_hr is not None:
                t["resting_hr"] = float(row.resting_hr)
            if row.steps is not None:
                t["steps"] = float(row.steps)
        # 主観チェックイン
        for row in s.execute(
            select(SubjectiveCheckin).where(
                SubjectiveCheckin.date >= start, SubjectiveCheckin.date <= target
            )
        ).scalars():
            f = _f(row.date)
            if row.energy is not None:
                f["subj_energy"] = float(row.energy)
            if row.stress is not None:
                f["subj_stress"] = float(row.stress)
            if row.soreness is not None:
                f["subj_soreness"] = float(row.soreness)
            if row.mood is not None:
                f["subj_mood"] = float(row.mood)
        # 気圧 (JST 日平均)
        press: dict[date_type, list[float]] = {}
        for ts, val in s.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.metric_key == "surface_pressure_hpa",
                MetricSample.ts >= ts_lo_dt, MetricSample.ts < ts_hi_dt,
            )
        ):
            if val is not None:
                press.setdefault(_jst_date(ts), []).append(float(val))
        press_mean = {d: sum(v) / len(v) for d, v in press.items()}
        # 前夜の飲酒 (前日 JST 合計) / 前日カフェイン
        alc: dict[date_type, float] = {}
        for ts, g in s.execute(
            select(AlcoholIntake.ts, AlcoholIntake.grams).where(
                AlcoholIntake.ts >= ts_lo_dt, AlcoholIntake.ts < ts_hi_dt
            )
        ):
            if g is not None:
                alc[_jst_date(ts)] = alc.get(_jst_date(ts), 0.0) + float(g)
        caf: dict[date_type, float] = {}
        for ts, mg in s.execute(
            select(CaffeineIntake.ts, CaffeineIntake.mg).where(
                CaffeineIntake.ts >= ts_lo_dt, CaffeineIntake.ts < ts_hi_dt
            )
        ):
            if mg is not None:
                caf[_jst_date(ts)] = caf.get(_jst_date(ts), 0.0) + float(mg)

    # カレンダー特徴 + 外部ログ特徴を全対象日に展開
    d = start
    while d <= target:
        f = _f(d)
        dow = d.weekday()
        f["weekend"] = 1.0 if dow >= 5 else 0.0
        f["dow_sin"] = math.sin(2 * math.pi * dow / 7)
        f["dow_cos"] = math.cos(2 * math.pi * dow / 7)
        f["month_sin"] = math.sin(2 * math.pi * d.month / 12)
        f["month_cos"] = math.cos(2 * math.pi * d.month / 12)
        f["moon"] = _moon_illumination(d)
        if d in press_mean:
            f["pressure_mean"] = press_mean[d]
            prev = press_mean.get(d - timedelta(days=1))
            if prev is not None:
                f["pressure_change"] = press_mean[d] - prev
        f["alcohol_prev"] = alc.get(d - timedelta(days=1), 0.0)
        f["caffeine_prev"] = caf.get(d - timedelta(days=1), 0.0)
        d += timedelta(days=1)

    return {"feats": feats, "tgts": tgts, "start": start}


def _zstats(feats: dict[date_type, dict[str, float]], keys: list[date_type]) -> dict[str, tuple[float, float]]:
    """各特徴の (mean, std) を履歴から算出 (std=0 は 1 に置換)。"""
    stats: dict[str, tuple[float, float]] = {}
    for fk in _FEATURE_WEIGHTS:
        vals = [feats[d][fk] for d in keys if fk in feats.get(d, {})]
        if len(vals) < 2:
            continue
        m = sum(vals) / len(vals)
        var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
        sd = math.sqrt(var) or 1.0
        stats[fk] = (m, sd)
    return stats


def _inertia(tgts: dict[date_type, dict[str, float]], metric: str, day: date_type) -> float | None:
    """day の直前 7 日で最後に実測できた同指標の値 (慣性)。"""
    for back in range(1, 8):
        v = tgts.get(day - timedelta(days=back), {}).get(metric)
        if v is not None:
            return v
    return None


def _distance(
    fq: dict[str, float], fd: dict[str, float], stats: dict[str, tuple[float, float]]
) -> float | None:
    """標準化重み付きユークリッド距離 (両者が持つ特徴のみ、重み正規化)。"""
    num = 0.0
    wsum = 0.0
    for fk, w in _FEATURE_WEIGHTS.items():
        if fk not in stats or fk not in fq or fk not in fd:
            continue
        m, sd = stats[fk]
        dz = (fq[fk] - m) / sd - (fd[fk] - m) / sd
        num += w * dz * dz
        wsum += w
    if wsum == 0:
        return None
    return math.sqrt(num / wsum)


def _drivers(fq: dict[str, float], stats: dict[str, tuple[float, float]]) -> list[str]:
    """当日の特徴のうち、推定を特徴づける目立つ条件を日本語ラベルで返す。"""
    out: list[str] = []
    if fq.get("alcohol_prev", 0) > 0:
        out.append("前夜の飲酒")
    if "pressure_change" in fq and "pressure_change" in stats:
        m, sd = stats["pressure_change"]
        if (fq["pressure_change"] - m) / sd < -1.0:
            out.append("気圧の低下")
        elif (fq["pressure_change"] - m) / sd > 1.0:
            out.append("気圧の上昇")
    if fq.get("weekend", 0) > 0:
        out.append("週末")
    if "subj_stress" in fq and fq["subj_stress"] >= 4:
        out.append("主観ストレス高")
    if "subj_energy" in fq and fq["subj_energy"] <= 2:
        out.append("主観活力低")
    if fq.get("caffeine_prev", 0) > 300:
        out.append("前日カフェイン多")
    return out[:3]


def impute_metric(metric: str, target: date_type, hist: dict[str, Any]) -> Imputed | None:
    """1 指標を kNN で補完。候補が乏しければ個人中央値へフォールバック。"""
    if metric not in METRICS:
        raise ValueError(f"unknown metric: {metric}")
    feats, tgts = hist["feats"], hist["tgts"]
    lo_clamp, hi_clamp = METRICS[metric]

    # 候補日 = 過去にその指標が実測されている日 (target は除く)
    cand_days = [d for d, t in tgts.items() if metric in t and d != target]
    if not cand_days:
        return None

    # 慣性特徴を query/候補に付与
    fq = dict(feats.get(target, {}))
    iq = _inertia(tgts, metric, target)
    if iq is not None:
        fq["inertia"] = iq

    stats = _zstats(feats, cand_days)
    # 慣性の stats は候補の慣性値から作る
    inertias = {d: _inertia(tgts, metric, d) for d in cand_days}
    ivals = [v for v in inertias.values() if v is not None]
    if len(ivals) >= 2:
        m = sum(ivals) / len(ivals)
        sd = math.sqrt(sum((v - m) ** 2 for v in ivals) / (len(ivals) - 1)) or 1.0
        stats["inertia"] = (m, sd)

    scored: list[tuple[float, float]] = []  # (distance, target_value)
    for d in cand_days:
        fd = dict(feats.get(d, {}))
        if inertias[d] is not None:
            fd["inertia"] = inertias[d]
        dist = _distance(fq, fd, stats)
        if dist is None:
            continue
        scored.append((dist, tgts[d][metric]))

    median_val = _median([tgts[d][metric] for d in cand_days])
    if len(scored) < _MIN_NEIGHBORS:
        return Imputed(metric, _clamp(median_val, lo_clamp, hi_clamp), "low", "baseline",
                       None, None, float(len(scored)), _drivers(fq, stats))

    scored.sort(key=lambda x: x[0])
    nn = scored[: _K]
    dists = [d for d, _ in nn]
    h = _median(dists) or 1.0  # バンド幅 = 近傍距離の中央値
    weights = [math.exp(-(d * d) / (2 * h * h)) for d, _ in nn]
    wsum = sum(weights) or 1.0
    value = sum(w * v for w, (_, v) in zip(weights, nn, strict=True)) / wsum
    # 加重分散 → 区間
    var = sum(w * (v - value) ** 2 for w, (_, v) in zip(weights, nn, strict=True)) / wsum
    spread = math.sqrt(max(var, 0.0))
    n_eff = (wsum * wsum) / (sum(w * w for w in weights) or 1.0)

    # 信頼度: 有効標本数 + 最近傍距離 (外挿) で段階化
    min_dist = dists[0]
    if min_dist > _FAR_Z or n_eff < 3:
        conf = "low"
    elif n_eff >= 6 and min_dist < 1.5:
        conf = "high"
    else:
        conf = "medium"

    value = _clamp(value, lo_clamp, hi_clamp)
    low = _clamp(value - spread, lo_clamp, hi_clamp)
    high = _clamp(value + spread, lo_clamp, hi_clamp)
    return Imputed(metric, value, conf, "knn", low, high, n_eff, _drivers(fq, stats))


def missing_metrics(target: date_type, hist: dict[str, Any]) -> list[str]:
    """target 当日に実測が欠けている指標キー一覧。"""
    have = hist["tgts"].get(target, {})
    return [m for m in METRICS if m not in have]


def impute_day(
    target: date_type | None = None, *, only_missing: bool = True
) -> dict[str, dict[str, Any]]:
    """当日の欠損指標を補完して {metric: imputed_dict} を返す。"""
    target = target or app_today()
    hist = _load_history(target)
    keys = missing_metrics(target, hist) if only_missing else list(METRICS)
    out: dict[str, dict[str, Any]] = {}
    for m in keys:
        imp = impute_metric(m, target, hist)
        if imp is not None:
            out[m] = imp.to_dict()
    return out


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

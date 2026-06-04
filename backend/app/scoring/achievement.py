"""理想値/理想帯からの達成度 (連続 0-100) を計算する DB 非依存の純粋関数群。

採点ロジック (daily_score) とは独立。トレンド表示専用。
全ての達成度は「高いほど理想に近い」に統一される。
"""

from __future__ import annotations

from app.scoring.baselines import Baseline

# 睡眠の合成重み (質側に重み)。後で調整可能。
SLEEP_TIME_WEIGHT = 0.4
SLEEP_QUALITY_WEIGHT = 0.6

# 睡眠時間の理想帯 (分) と減衰幅。
SLEEP_BAND_LO = 420
SLEEP_BAND_HI = 540
SLEEP_BAND_SOFTNESS = 90

# エネルギー (Body Battery) の片側パラメータ。
ENERGY_FLOOR = 20.0
ENERGY_GOOD = 80.0

# 運動負荷 (ACWR) の理想帯。
LOAD_BAND_LO = 0.8
LOAD_BAND_HI = 1.3
LOAD_BAND_SOFTNESS = 0.3


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def band_achievement(value: float, lo: float, hi: float, softness: float) -> float:
    """理想帯 [lo, hi] 内で 100、外側はローレンツ関数で滑らかに減衰。"""
    if lo <= value <= hi:
        return 100.0
    d = min(abs(value - lo), abs(value - hi))
    s = softness if softness > 1e-9 else 1e-9
    return 100.0 / (1.0 + (d / s) ** 2)


def upper_achievement(value: float, floor: float, good: float) -> float:
    """floor で 0、good 以上で 100、間は線形 (高いほど良い指標)。"""
    if good <= floor:
        return 100.0 if value >= good else 0.0
    return _clamp((value - floor) / (good - floor) * 100.0)


def _quality_achievement(
    garmin_sleep_score: float | None,
    deep_min: int | None,
    rem_min: int | None,
    light_min: int | None,
    awake_min: int | None,
) -> float | None:
    """睡眠の質達成度。Garmin スコア優先、無ければ効率 + deep/rem 比。"""
    if garmin_sleep_score is not None:
        return _clamp(float(garmin_sleep_score))
    if None in (deep_min, rem_min, light_min, awake_min):
        return None
    in_bed = deep_min + rem_min + light_min + awake_min
    if in_bed <= 0:
        return None
    efficiency = (in_bed - awake_min) / in_bed * 100
    ratio = (deep_min + rem_min) / in_bed
    ratio_score = _clamp(50 + (ratio - 0.20) * 250)
    return _clamp((efficiency + ratio_score) / 2)


def sleep_achievement(
    *,
    total_min: int | None,
    garmin_sleep_score: float | None,
    deep_min: int | None,
    rem_min: int | None,
    light_min: int | None,
    awake_min: int | None,
) -> float | None:
    """睡眠の合成達成度 = 0.4*時間 + 0.6*質 (質が無い日は時間のみ)。"""
    if total_min is None or total_min <= 0:
        return None
    time_ach = band_achievement(float(total_min), SLEEP_BAND_LO, SLEEP_BAND_HI, SLEEP_BAND_SOFTNESS)
    quality_ach = _quality_achievement(garmin_sleep_score, deep_min, rem_min, light_min, awake_min)
    if quality_ach is None:
        return time_ach
    return _clamp(SLEEP_TIME_WEIGHT * time_ach + SLEEP_QUALITY_WEIGHT * quality_ach)


def hrv_achievement(value: float | None, baseline: Baseline | None) -> float | None:
    if value is None or baseline is None:
        return None
    z = (float(value) - baseline.mean) / baseline.std
    z = max(-2.0, min(2.0, z))
    return _clamp(50.0 + 25.0 * z)


def energy_achievement(morning_value: float | None) -> float | None:
    if morning_value is None:
        return None
    return upper_achievement(float(morning_value), ENERGY_FLOOR, ENERGY_GOOD)


def load_achievement(acwr: float | None) -> float | None:
    if acwr is None:
        return None
    return band_achievement(float(acwr), LOAD_BAND_LO, LOAD_BAND_HI, LOAD_BAND_SOFTNESS)


def weight_achievement(value: float | None, target_kg: float) -> float | None:
    if value is None or target_kg <= 0:
        return None
    return band_achievement(float(value), target_kg - 1.0, target_kg + 1.0, 1.5)


def body_fat_achievement(value: float | None, target_pct: float, tol: float) -> float | None:
    if value is None or target_pct <= 0:
        return None
    return band_achievement(float(value), target_pct - tol, target_pct + tol, max(tol * 2, 0.5))

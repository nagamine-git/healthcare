from __future__ import annotations

from app.scoring.baselines import Baseline


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def sleep_subscore(
    *,
    garmin_sleep_score: float | None,
    total_min: int | None,
    deep_min: int | None = None,
    rem_min: int | None = None,
    light_min: int | None = None,
    awake_min: int | None = None,
) -> float | None:
    if garmin_sleep_score is not None:
        return _clamp(float(garmin_sleep_score))

    if total_min is None or total_min <= 0:
        return None

    # Duration sub: target band 7-9h (420-540 min). Triangular peak at 480.
    if total_min < 240:
        duration_score = 0.0
    elif total_min < 420:
        duration_score = 50 + (total_min - 240) / 180 * 40  # 50 → 90 between 4h and 7h
    elif total_min <= 540:
        duration_score = 100.0
    elif total_min <= 660:
        duration_score = 100 - (total_min - 540) / 120 * 30  # 100 → 70 between 9h and 11h
    else:
        duration_score = 60.0

    components = [duration_score]

    if (
        deep_min is not None
        and rem_min is not None
        and light_min is not None
        and awake_min is not None
    ):
        in_bed = deep_min + rem_min + light_min + awake_min
        if in_bed > 0:
            efficiency = (in_bed - awake_min) / in_bed * 100
            components.append(_clamp(efficiency))
            ratio = (deep_min + rem_min) / max(in_bed, 1)
            # Healthy combined deep+REM ratio ~30-40%
            ratio_score = _clamp(50 + (ratio - 0.20) * 250, 0, 100)
            components.append(ratio_score)

    return _clamp(sum(components) / len(components))


def hrv_subscore(value: float | None, baseline: Baseline | None) -> float | None:
    if value is None or baseline is None:
        return None
    z = (float(value) - baseline.mean) / baseline.std
    z = max(-2.0, min(2.0, z))
    return _clamp(50.0 + 25.0 * z)


def body_battery_subscore(*, morning_value: float | None) -> float | None:
    if morning_value is None:
        return None
    return _clamp(float(morning_value))


def training_load_subscore(*, acute: float | None, chronic: float | None) -> float | None:
    if acute is None or chronic is None:
        return None
    if chronic <= 0:
        return None
    ratio = float(acute) / float(chronic)
    if 0.8 <= ratio <= 1.3:
        return 85.0
    if 0.5 <= ratio < 0.8 or 1.3 < ratio <= 1.5:
        return 65.0
    return 40.0


def weight_subscore(
    *, recent_median: float | None, baseline: Baseline | None
) -> float | None:
    if recent_median is None or baseline is None:
        return None
    z = abs((float(recent_median) - baseline.mean) / baseline.std)
    if z <= 1.0:
        return 80.0
    if z <= 2.0:
        return 50.0
    return 30.0


def body_fat_subscore(
    *,
    recent_value: float | None,
    target_pct: float,
    tolerance_pct: float = 1.5,
) -> float | None:
    """目標体脂肪率からの偏差で 0-100。

    - 目標 ±tolerance: 90 (ほぼゴール)
    - 目標 ±2*tolerance: 75
    - 目標 ±3*tolerance: 55
    - それ以遠: 40 (上回るほど低スコアにせず、フラットにして「焦らない」設計)

    target からの「下振れ」も上振れも同じ重みで罰する。極端に絞るのは健康・仕事
    パフォーマンスと両立しないため。
    """
    if recent_value is None or target_pct <= 0:
        return None
    diff = abs(float(recent_value) - float(target_pct))
    if diff <= tolerance_pct:
        return 90.0
    if diff <= tolerance_pct * 2:
        return 75.0
    if diff <= tolerance_pct * 3:
        return 55.0
    return 40.0

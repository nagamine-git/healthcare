"""主観チェックインの「目安」を客観指標から推定する純関数。

自己履歴が無いコールドスタートでも、関連する客観データから 1-5 の目安を薄く出す。
あくまで推定 (proxy) であり、ユーザーの実入力が優先される。
"""

from __future__ import annotations


def _clamp5(v: float) -> int:
    return max(1, min(5, round(v)))


def _band_0_100_to_5(v: float) -> int:
    """0-100 を 1-5 に区分 (80+ →5, 60+ →4, 40+ →3, 20+ →2, 他 →1)。"""
    if v >= 80:
        return 5
    if v >= 60:
        return 4
    if v >= 40:
        return 3
    if v >= 20:
        return 2
    return 1


def _stress_from_garmin(stress_avg: float | None) -> int | None:
    """Garmin ストレス (0-100) → ストレス 1-5 (高いほど大)。

    Garmin の帯域: 0-25 休息 / 26-50 低 / 51-75 中 / 76-100 高。
    """
    if stress_avg is None:
        return None
    if stress_avg < 25:
        return 1
    if stress_avg < 40:
        return 2
    if stress_avg < 55:
        return 3
    if stress_avg < 70:
        return 4
    return 5


def _soreness_from_load(training_load_48h: float | None) -> int | None:
    """直近48hのトレ負荷合計 → 筋肉痛 1-5 (DOMS は 24-48h で顕在化)。"""
    if training_load_48h is None:
        return None
    load = training_load_48h
    if load <= 0:
        return 1
    if load < 100:
        return 2
    if load < 200:
        return 3
    if load < 300:
        return 4
    return 5


def estimate_subjective(
    *,
    body_battery: float | None,
    stress_avg: float | None,
    sleep_score: float | None,
    training_load_48h: float | None,
    training_readiness: float | None = None,
) -> dict[str, int | None]:
    """各次元の目安 (1-5) を返す。proxy が無い次元は None。"""
    # 活力: Body Battery を主とし、無い場合のみ Training Readiness で代用。
    # Readiness は HRV/睡眠/BB を内包する合成指標なので、BB と平均すると
    # 同じ情報を二重計上することになる (独立な観測ではない)。
    if body_battery is not None:
        energy = _band_0_100_to_5(body_battery)
    elif training_readiness is not None:
        energy = _band_0_100_to_5(training_readiness)
    else:
        energy = None
    stress = _stress_from_garmin(stress_avg)
    soreness = _soreness_from_load(training_load_48h)

    # 気分: 睡眠・活力(BB)・低ストレス の合成 (取れるものだけ平均)。最も軟らかい推定。
    mood_parts: list[float] = []
    if sleep_score is not None:
        mood_parts.append(sleep_score / 20.0)
    if energy is not None:
        mood_parts.append(float(energy))
    if stress is not None:
        mood_parts.append(float(6 - stress))  # ストレス反転 (低ストレス=良い気分寄り)
    mood = _clamp5(sum(mood_parts) / len(mood_parts)) if mood_parts else None

    return {"mood": mood, "energy": energy, "stress": stress, "soreness": soreness}

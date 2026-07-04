"""体型指標 (BMI / 体脂肪率 / FFMI) の母集団基準値と percentile。

日本人 同年代・同性の母集団に対する「自分の現在地」を percentile で示すための
純粋ロジック。基準値はコードに保持し、正規分布 CDF で percentile を返す。

# 出典・確度
- BMI: 平成28年 国民健康・栄養調査 (e-Stat 0003224178) の男性実測 (平均・標準偏差)。
       女性は同調査の近似。→ 公的統計ベースで確度は高い。
- 体脂肪率 / FFMI: 信頼できる年代別母集団分布が乏しいため、文献ベースの「目安」。
       値そのもの (体重・体脂肪率・身長からの計算) は正確だが、percentile は参考値。

# FFMI (除脂肪量指数)
除脂肪量 = 体重 ×(1 − 体脂肪率/100)、FFMI = 除脂肪量 / 身長²。
BMI が見ない「筋肉質さ」を表す。
"""

from __future__ import annotations

import math

# metric -> sex -> [(age_lo, age_hi, mean, sd), ...] (年齢は両端含む)
NORMS: dict[str, dict[str, list[tuple[int, int, float, float]]]] = {
    "bmi": {  # 平成28年 国民健康・栄養調査 (男性実測 / 女性は近似)
        "male": [(18, 29, 22.6, 3.7), (30, 49, 23.9, 3.6), (50, 69, 24.0, 2.9), (70, 200, 23.4, 2.9)],
        "female": [(18, 29, 20.7, 2.8), (30, 49, 21.7, 3.4), (50, 69, 22.9, 3.5), (70, 200, 23.1, 3.7)],
    },
    "body_fat": {  # 文献の目安
        "male": [(18, 29, 16.0, 5.0), (30, 49, 20.0, 5.0), (50, 69, 23.0, 5.0), (70, 200, 24.0, 5.0)],
        "female": [(18, 29, 25.0, 6.0), (30, 49, 28.0, 6.0), (50, 69, 31.0, 6.0), (70, 200, 32.0, 6.0)],
    },
    "ffmi": {  # 文献の目安
        "male": [(18, 29, 18.9, 1.9), (30, 49, 18.9, 1.9), (50, 69, 18.3, 1.9), (70, 200, 17.6, 1.9)],
        "female": [(18, 29, 14.6, 1.6), (30, 49, 14.6, 1.6), (50, 69, 14.2, 1.6), (70, 200, 13.8, 1.6)],
    },
    "vo2max": {  # ml/kg/min。ACSM/FRIEND レジストリ等の目安 (高いほど良い)
        "male": [(18, 29, 46.0, 8.0), (30, 49, 41.0, 8.0), (50, 69, 33.0, 7.0), (70, 200, 27.0, 6.0)],
        "female": [(18, 29, 37.0, 7.0), (30, 49, 33.0, 7.0), (50, 69, 27.0, 6.0), (70, 200, 22.0, 5.0)],
    },
}

SOURCES = {
    "bmi": "国民健康・栄養調査",
    "body_fat": "文献の目安",
    "ffmi": "文献の目安",
    "vo2max": "ACSM/FRIENDの目安",
}


def metric_source(metric: str) -> str:
    return SOURCES.get(metric, "")


def norm_for(metric: str, age: int | None, sex: str | None) -> tuple[float, float] | None:
    """年代帯から (mean, sd) を返す。該当帯が無ければ None。"""
    if age is None or sex is None:
        return None
    table = NORMS.get(metric, {}).get(sex)
    if not table:
        return None
    for lo, hi, mean, sd in table:
        if lo <= age <= hi:
            return (mean, sd)
    return None


def _phi(z: float) -> float:
    """標準正規分布の累積分布関数。"""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def pct_from(value: float | None, mean: float | None, sd: float | None) -> float | None:
    """mean/sd の正規分布で value が下位から何%地点か (0-100)。汎用・体力テストでも再利用。"""
    if value is None or mean is None or sd is None or sd <= 0:
        return None
    p = _phi((value - mean) / sd) * 100.0
    return max(0.0, min(100.0, p))


def percentile(metric: str, value: float | None, age: int | None, sex: str | None) -> float | None:
    """value が母集団で下位から何%地点か (0-100)。算出不能なら None。"""
    band = norm_for(metric, age, sex)
    if band is None:
        return None
    return pct_from(value, band[0], band[1])


def _r(x: float | None) -> float | None:
    return round(x, 1) if x is not None else None


def _metric(
    key: str,
    label: str,
    unit: str,
    value: float | None,
    age: int | None,
    sex: str | None,
    target_low: float | None,
    target_high: float | None,
    evaluable: bool,
) -> dict:
    band = norm_for(key, age, sex) if evaluable else None
    # 範囲は低い方を low に揃える (体脂肪率の許容幅から導くと逆転し得るため)。
    lo, hi = target_low, target_high
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "value": _r(value),
        "mean": band[0] if band else None,
        "sd": band[1] if band else None,
        "percentile": (
            round(p, 1) if evaluable and (p := percentile(key, value, age, sex)) is not None else None
        ),
        "source": metric_source(key),
        "target_low": _r(lo),
        "target_high": _r(hi),
    }


def build_distribution(
    weight_kg: float | None,
    body_fat_pct: float | None,
    age: int | None,
    sex: str | None,
    height_cm: float | None,
    target_weight_kg: float | None = None,
    target_body_fat_pct: float | None = None,
    body_fat_tolerance_pct: float | None = None,
    vo2max: float | None = None,
    vo2max_estimated: bool = False,
) -> dict:
    """体型4指標 (BMI/体脂肪率/FFMI/心肺VO2max) の値・母集団mean/sd・percentile・目標範囲をまとめる。

    年齢/性別/身長が揃い、性別が基準値を持つときのみ evaluable=True (percentile を出す)。
    値そのものは evaluable に関わらず算出可能なら返す。VO2max は Garmin 実測の最新値。

    目標は 3 指標とも範囲 (帯) で表す。体脂肪率の許容幅 (tol) を共通の源にし、各指標を
    その指標にとって自然な変動で帯化する:
    - 体脂肪率: 目標 ± tol。
    - BMI: 「除脂肪量 (筋肉目標) 一定のまま体脂肪率が ±tol 振れたら体重がどう動くか」の体重
      スイングから BMI 範囲を出す (BMI は体重だけで決まるため)。
    - FFMI: 目標体重を保ったまま体脂肪率が ±tol で動くと除脂肪量→FFMI が動く、その範囲。
    tol=0 なら各範囲は 1 点に縮退する。
    """
    evaluable = bool(
        age is not None and sex in NORMS["bmi"] and height_cm and height_cm > 0
    )
    bmi_v = bmi(weight_kg, height_cm)
    ffmi_v = ffmi(weight_kg, body_fat_pct, height_cm)

    tol = body_fat_tolerance_pct or 0.0
    h = height_cm / 100.0 if height_cm and height_cm > 0 else None
    target_ffm = (
        target_weight_kg * (1.0 - target_body_fat_pct / 100.0)
        if target_weight_kg and target_body_fat_pct is not None
        else None
    )

    # 体脂肪率の目標範囲
    bf_lo = target_body_fat_pct - tol if target_body_fat_pct is not None else None
    bf_hi = target_body_fat_pct + tol if target_body_fat_pct is not None else None

    # BMI: 除脂肪量一定で体脂肪率 bf のときの体重 → BMI (体脂肪高→体重大→BMI大)
    def _bmi_at_bf(bf: float | None) -> float | None:
        if target_ffm is None or bf is None or bf >= 100 or height_cm is None:
            return None
        w = target_ffm / (1.0 - bf / 100.0)
        return bmi(w, height_cm)

    bmi_lo = _bmi_at_bf(bf_lo)  # 体脂肪率が低い → 体重小 → BMI 低
    bmi_hi = _bmi_at_bf(bf_hi)  # 体脂肪率が高い → 体重大 → BMI 高

    # FFMI: 目標体重を固定し、体脂肪率 bf のときの除脂肪量 → FFMI
    def _ffmi_at_bf(bf: float | None) -> float | None:
        if not target_weight_kg or bf is None or h is None:
            return None
        ffm = target_weight_kg * (1.0 - bf / 100.0)
        return ffm / (h * h)

    ffmi_lo = _ffmi_at_bf(bf_hi)  # 体脂肪率が高い → FFMI 低
    ffmi_hi = _ffmi_at_bf(bf_lo)  # 体脂肪率が低い → FFMI 高

    metrics = [
        _metric("bmi", "BMI", "", bmi_v, age, sex, bmi_lo, bmi_hi, evaluable),
        _metric("body_fat", "体脂肪率", "%", body_fat_pct, age, sex, bf_lo, bf_hi, evaluable),
        _metric("ffmi", "FFMI (筋肉量指数)", "", ffmi_v, age, sex, ffmi_lo, ffmi_hi, evaluable),
        _metric(
            "vo2max", "心肺フィットネス (VO2max)", "ml/kg/min", vo2max, age, sex, None, None, evaluable
        ),
    ]
    # Garmin 実測が無い期間は公表式による推定値で代替することがある (出所を明示)
    if vo2max is not None and vo2max_estimated:
        metrics[-1]["estimated"] = True
    return {"evaluable": evaluable, "metrics": metrics}


def bmi(weight_kg: float | None, height_cm: float | None) -> float | None:
    if not weight_kg or not height_cm or height_cm <= 0:
        return None
    h = height_cm / 100.0
    return weight_kg / (h * h)


def ffmi(
    weight_kg: float | None, body_fat_pct: float | None, height_cm: float | None
) -> float | None:
    """除脂肪量指数。体脂肪率が無いと算出不能。"""
    if weight_kg is None or body_fat_pct is None or not height_cm or height_cm <= 0:
        return None
    ffm = weight_kg * (1.0 - body_fat_pct / 100.0)
    h = height_cm / 100.0
    return ffm / (h * h)

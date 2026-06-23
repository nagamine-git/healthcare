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
}

SOURCES = {
    "bmi": "国民健康・栄養調査",
    "body_fat": "文献の目安",
    "ffmi": "文献の目安",
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


def percentile(metric: str, value: float | None, age: int | None, sex: str | None) -> float | None:
    """value が母集団で下位から何%地点か (0-100)。算出不能なら None。"""
    if value is None:
        return None
    band = norm_for(metric, age, sex)
    if band is None:
        return None
    mean, sd = band
    if sd <= 0:
        return None
    p = _phi((value - mean) / sd) * 100.0
    return max(0.0, min(100.0, p))


def _metric(
    key: str,
    label: str,
    unit: str,
    value: float | None,
    age: int | None,
    sex: str | None,
    target: float | None,
    evaluable: bool,
) -> dict:
    band = norm_for(key, age, sex) if evaluable else None
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "value": round(value, 1) if value is not None else None,
        "mean": band[0] if band else None,
        "sd": band[1] if band else None,
        "percentile": (
            round(p, 1) if evaluable and (p := percentile(key, value, age, sex)) is not None else None
        ),
        "source": metric_source(key),
        "target": round(target, 1) if target is not None else None,
    }


def build_distribution(
    weight_kg: float | None,
    body_fat_pct: float | None,
    age: int | None,
    sex: str | None,
    height_cm: float | None,
    target_weight_kg: float | None = None,
    target_body_fat_pct: float | None = None,
) -> dict:
    """体型3指標 (BMI/体脂肪率/FFMI) の値・母集団mean/sd・percentile・目標をまとめる。

    年齢/性別/身長が揃い、性別が基準値を持つときのみ evaluable=True (percentile を出す)。
    値そのものは evaluable に関わらず算出可能なら返す。
    """
    evaluable = bool(
        age is not None and sex in NORMS["bmi"] and height_cm and height_cm > 0
    )
    bmi_v = bmi(weight_kg, height_cm)
    ffmi_v = ffmi(weight_kg, body_fat_pct, height_cm)
    target_bmi = bmi(target_weight_kg, height_cm)
    metrics = [
        _metric("bmi", "BMI", "", bmi_v, age, sex, target_bmi, evaluable),
        _metric("body_fat", "体脂肪率", "%", body_fat_pct, age, sex, target_body_fat_pct, evaluable),
        _metric("ffmi", "FFMI (筋肉量指数)", "", ffmi_v, age, sex, None, evaluable),
    ]
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

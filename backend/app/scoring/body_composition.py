"""理想体型 (体脂肪率 × FFMI) から目標体重を求める純関数群。

画像 1 枚から体脂肪率の絶対値は測れないため、校正済み参照シルエット
(体脂肪率と FFMI でタグ付け) を選ぶ前提。選んだ体組成と身長から目標体重を導出する。

FFMI (Fat-Free Mass Index) = 除脂肪量(kg) / 身長(m)^2。
正規化 FFMI は身長差を補正した値で、男性は ~18 平均 / 20 で athletic / 22 でかなり筋肉質。
"""

from __future__ import annotations

from typing import Any

# UI と共有する参照シルエットの軸
BUILD_OPTIONS = [
    {"key": "slim", "label": "細身", "ffmi": 18.0},
    {"key": "lean_muscular", "label": "細マッチョ", "ffmi": 20.0},
    {"key": "muscular", "label": "マッチョ", "ffmi": 22.0},
]
BODY_FAT_OPTIONS = [10.0, 12.0, 15.0, 18.0, 22.0]

# 体脂肪率の健康下限 (性別)。これ未満はホルモン・免疫・気分への影響が出やすい。
BODY_FAT_FLOOR = {"male": 10.0, "female": 16.0}

BMI_UNDERWEIGHT = 18.5
BMI_SEVERE = 16.0


def compute_target(height_cm: float, body_fat_pct: float, ffmi_normalized: float) -> dict[str, float]:
    """身長・目標体脂肪率・正規化 FFMI から目標体重・BMI・除脂肪量を返す。"""
    height_m = height_cm / 100.0
    # 正規化 FFMI から実 FFMI を逆算 (Kouri 1995 の身長補正 6.1*(1.8-h))
    ffmi_raw = ffmi_normalized - 6.1 * (1.8 - height_m)
    lbm_kg = ffmi_raw * height_m**2
    bf = max(0.0, min(60.0, body_fat_pct)) / 100.0
    weight_kg = lbm_kg / (1.0 - bf) if bf < 1.0 else lbm_kg
    bmi = weight_kg / height_m**2
    return {
        "weight_kg": round(weight_kg, 1),
        "bmi": round(bmi, 1),
        "lbm_kg": round(lbm_kg, 1),
    }


def assess(*, weight_kg: float, bmi: float, body_fat_pct: float, sex: str) -> dict[str, Any]:
    """目標体組成の安全性を評価する。level: ok | warning | blocked。"""
    warnings: list[str] = []
    level = "ok"

    if bmi < BMI_SEVERE:
        level = "blocked"
        warnings.append(f"BMI {bmi:.1f} は重度の低体重域です。この目標は保存できません")
    elif bmi < BMI_UNDERWEIGHT:
        level = "warning"
        warnings.append(f"BMI {bmi:.1f} は低体重域 (18.5 未満) です")

    floor = BODY_FAT_FLOOR.get(sex, 10.0)
    if body_fat_pct < floor:
        if level != "blocked":
            level = "warning"
        warnings.append(
            f"体脂肪 {body_fat_pct:.0f}% は{'男性' if sex == 'male' else '女性'}の健康下限"
            f" ({floor:.0f}%) を下回り、持続が難しくホルモンへの影響が出やすい"
        )

    return {"level": level, "warnings": warnings}

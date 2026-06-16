"""UI 設定の個人プロファイルと env デフォルトを統合する resolve 層。

config.py (env) はデフォルト/例プロファイルを持ち、UI で上書きした値は
user_profile テーブル (単一行) に入る。採点・アラート・LLM・栄養はこの
resolve_profile() を経由して「有効なプロファイル」を読む。

計算直結の個人差ファクター (年齢・心拍・カフェイン PK・睡眠・栄養) を含み、
派生値 (有効半減期・目標 mg/kg・最大心拍) はここで一元的に計算する。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.db import session_scope
from app.models import UserProfile

# カフェイン感受性 → 目標 mg/kg。high=効きやすいので少なめ、low=多め。
_SENSITIVITY_MG_PER_KG = {"high": 0.5, "normal": 1.0, "low": 1.5}
# CYP1A2 修飾因子による消失半減期の乗数 (ベース ~5h)。
_SMOKER_MULT = 0.6  # 喫煙は誘導でクリアランス↑ → 半減期短縮 (Parsons & Neims 1978)
_OC_MULT = 1.8  # 経口避妊薬 (ethinylestradiol) は阻害で半減期延長
_PREGNANT_MULT = 2.6  # 妊娠後期は強い阻害 (最大 ~3x)
_HALF_LIFE_MIN, _HALF_LIFE_MAX = 2.0, 12.0


def derive_caffeine_half_life_h(
    base_h: float,
    *,
    smoker: bool,
    oral_contraceptives: bool,
    pregnant: bool,
    override_h: float | None,
) -> float:
    """CYP1A2 修飾因子からカフェイン消失半減期を導出 ([2,12]h にクランプ)。"""
    if override_h is not None:
        return max(_HALF_LIFE_MIN, min(_HALF_LIFE_MAX, override_h))
    h = base_h
    if smoker:
        h *= _SMOKER_MULT
    if oral_contraceptives:
        h *= _OC_MULT
    if pregnant:
        h *= _PREGNANT_MULT
    return max(_HALF_LIFE_MIN, min(_HALF_LIFE_MAX, h))


def derive_target_mg_per_kg(sensitivity: str, default: float) -> float:
    return _SENSITIVITY_MG_PER_KG.get(sensitivity, default)


def derive_max_hr(override: int | None, age: int) -> int:
    """実測上書きが無ければ Tanaka 式 (208 - 0.7*age, Tanaka 2001) で推定。"""
    if override:
        return int(override)
    return round(208 - 0.7 * age)


@dataclass(frozen=True)
class ResolvedProfile:
    height_cm: float
    sex: str
    target_weight_kg: float
    target_body_fat_pct: float
    body_fat_tolerance_pct: float
    ffmi_normalized: float | None
    # 個人差ファクター
    age: int
    resting_hr: int
    max_hr: int  # 派生 (override or 式)
    caffeine_smoker: bool
    caffeine_oral_contraceptives: bool
    caffeine_pregnant: bool
    caffeine_sensitivity: str
    caffeine_half_life_override_h: float | None
    caffeine_half_life_h: float  # 派生
    caffeine_target_mg_per_kg: float  # 派生
    wake_time: str
    sleep_need_min: int
    chronotype: str
    protein_g_per_kg: float
    water_ml_per_kg: float
    source: str  # "db" | "default"


def resolve_profile() -> ResolvedProfile:
    """DB 上書きを env デフォルトにマージした有効プロファイルを返す。

    フィールド単位でフォールバックする (DB 行はあるが特定フィールドが NULL なら
    そのフィールドだけ settings を使う)。
    """
    s = get_settings()
    with session_scope() as session:
        row = session.get(UserProfile, 1)

        def pick(attr: str, default):
            if row is None:
                return default
            v = getattr(row, attr, None)
            return v if v is not None else default

        age = int(pick("age", s.user_age))
        caffeine_smoker = bool(pick("caffeine_smoker", False))
        caffeine_oc = bool(pick("caffeine_oral_contraceptives", False))
        caffeine_pregnant = bool(pick("caffeine_pregnant", False))
        caffeine_sensitivity = pick("caffeine_sensitivity", s.caffeine_sensitivity)
        half_life_override = pick("caffeine_half_life_override_h", None)
        max_hr_override = pick("max_hr", s.user_max_hr)

        return ResolvedProfile(
            height_cm=pick("height_cm", s.user_height_cm),
            sex=pick("sex", s.user_sex),
            target_weight_kg=pick("target_weight_kg", s.target_weight_kg),
            target_body_fat_pct=pick("target_body_fat_pct", s.target_body_fat_pct),
            body_fat_tolerance_pct=pick("body_fat_tolerance_pct", s.body_fat_tolerance_pct),
            ffmi_normalized=row.ffmi_normalized if row is not None else None,
            age=age,
            resting_hr=int(pick("resting_hr", s.user_resting_hr)),
            max_hr=derive_max_hr(max_hr_override, age),
            caffeine_smoker=caffeine_smoker,
            caffeine_oral_contraceptives=caffeine_oc,
            caffeine_pregnant=caffeine_pregnant,
            caffeine_sensitivity=caffeine_sensitivity,
            caffeine_half_life_override_h=half_life_override,
            caffeine_half_life_h=derive_caffeine_half_life_h(
                s.caffeine_half_life_h,
                smoker=caffeine_smoker,
                oral_contraceptives=caffeine_oc,
                pregnant=caffeine_pregnant,
                override_h=half_life_override,
            ),
            caffeine_target_mg_per_kg=derive_target_mg_per_kg(
                caffeine_sensitivity, s.caffeine_target_mg_per_kg
            ),
            wake_time=pick("wake_time", s.target_wake_time),
            sleep_need_min=int(pick("sleep_need_min", s.target_sleep_min)),
            chronotype=pick("chronotype", s.user_chronotype),
            protein_g_per_kg=pick("protein_g_per_kg", s.target_protein_g_per_kg),
            water_ml_per_kg=pick("water_ml_per_kg", s.target_water_ml_per_kg),
            source="db" if row is not None else "default",
        )

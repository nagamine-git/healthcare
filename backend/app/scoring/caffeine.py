"""カフェイン薬物動態モデルと「今飲める量」の推定。

# モデル
1-コンパートメント、即時吸収・1次消失 (典型的な急性カフェイン薬物動態の近似)。

    C(t) = (D / Vd) * exp(-k * t)
    k     = ln(2) / T_half
    Vd    ≈ 0.5 L/kg  (Tang-Liu 1983, Kaplan 1997)
    T_half = 5h (健常成人の平均、個人差 2-12h、CYP1A2 遺伝多型・喫煙・経口避妊薬で変動)

# 安全閾値
就寝時血中カフェイン濃度が **0.5 mg/L 未満** になるように設計。
Drake 2013 (J Clin Sleep Med) では bedtime 6h 前の 400mg 摂取で睡眠分断が
有意に増加。10-20% 残量 (50-80mg) で 60-70kg 体重を仮定すると C ≈ 0.8-1.6 mg/L。
0.5 mg/L 以下は安全域とされる Roehrs & Roth 2008 の議論を採用。

# 認知効果の最低有効量
Smith 2002 (Food Chem Toxicol) メタ解析より、注意・反応時間の改善は
**約 60mg (1mg/kg, 60kg)** から有意。本実装では `min_cognitive_mg` を
設定値とし (デフォルト 60mg)、これを下回る推奨は出さない。

# インスタントコーヒー換算
市販のインスタントコーヒー (AGF / Nescafe / UCC) は **1g あたり 50-65mg** の
カフェインを含む。ブレンドにより変動。設定値 `instant_coffee_mg_per_g` で調整可。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta


def half_life_decay(dose_mg: float, hours_elapsed: float, *, half_life_h: float = 5.0) -> float:
    """摂取量 dose_mg が hours_elapsed 後に体内に残る量 (mg)。"""
    if dose_mg <= 0 or hours_elapsed < 0:
        return 0.0
    return dose_mg * math.exp(-math.log(2) * hours_elapsed / half_life_h)


def blood_concentration(
    dose_mg: float,
    hours_elapsed: float,
    *,
    body_weight_kg: float,
    half_life_h: float = 5.0,
    vd_l_per_kg: float = 0.5,
) -> float:
    """t 時間後の推定血中カフェイン濃度 (mg/L)。"""
    if body_weight_kg <= 0:
        return 0.0
    remaining = half_life_decay(dose_mg, hours_elapsed, half_life_h=half_life_h)
    return remaining / (vd_l_per_kg * body_weight_kg)


def max_dose_for_bedtime(
    *,
    hours_until_bedtime: float,
    body_weight_kg: float,
    bedtime_threshold_mg_per_l: float = 0.5,
    half_life_h: float = 5.0,
    vd_l_per_kg: float = 0.5,
    existing_residual_mg: float = 0.0,
) -> float:
    """就寝時に血中濃度 ≤ bedtime_threshold_mg_per_l を満たす最大新規摂取量 (mg)。

    `existing_residual_mg` は今までに摂取済みカフェインのうち「今この瞬間」体内に
    残っている量。これも同じ消失曲線で就寝時に減衰する想定。
    """
    if hours_until_bedtime <= 0:
        return 0.0

    decay = math.exp(-math.log(2) * hours_until_bedtime / half_life_h)
    # 就寝時残量 (mg) = (D_new + existing) * decay
    # これを Vd * BW で割って bedtime_threshold 以下にしたい:
    #   (D_new + existing) * decay / (Vd * BW) ≤ threshold
    #   D_new ≤ threshold * Vd * BW / decay - existing
    allowable_total_now = bedtime_threshold_mg_per_l * vd_l_per_kg * body_weight_kg / decay
    return max(0.0, allowable_total_now - existing_residual_mg)


@dataclass(frozen=True)
class CaffeineRecommendation:
    recommended_mg: float | None  # None なら「飲まない方が良い」
    instant_coffee_g: float | None
    max_safe_mg: float  # bedtime 制約での上限
    min_cognitive_mg: float  # 認知効果の下限 (設定値)
    hours_until_bedtime: float
    bedtime_residual_if_consumed_mg: float  # recommended_mg を今飲んだ場合の就寝時残量
    blood_concentration_at_bedtime_mg_per_l: float
    half_life_h: float
    reason: str  # 「推奨/非推奨」の根拠を 1 文


def recommend_caffeine(
    *,
    now: datetime,
    bedtime_jst_hhmm: str,
    body_weight_kg: float,
    half_life_h: float = 5.0,
    vd_l_per_kg: float = 0.5,
    bedtime_threshold_mg_per_l: float = 0.5,
    min_cognitive_mg: float = 60.0,
    target_dose_mg_per_kg: float = 1.0,
    instant_coffee_mg_per_g: float = 60.0,
    existing_residual_mg: float = 0.0,
    cutoff_hours_before_bed: float = 6.0,
) -> CaffeineRecommendation:
    """現時点でのカフェイン摂取の最適提案を返す。

    Args:
        now: 現在時刻 (JST aware datetime)
        bedtime_jst_hhmm: 今夜の就寝時刻 "HH:MM" 形式
        body_weight_kg: 体重 (Vd 計算で必要)
        target_dose_mg_per_kg: 目標摂取量 (mg/kg)。1.0 が認知改善の典型量、
            高感受性者は 0.5-0.75、低感受性は 1.5-2.0
        cutoff_hours_before_bed: bedtime までこの時間を切ったら最低量も推奨しない
            (デフォルト 6h、Drake 2013 ベース)
        existing_residual_mg: 今この瞬間体内に残ってる推定量
    """
    bed_time = _parse_hhmm(bedtime_jst_hhmm)
    bedtime_dt = _next_occurrence(now, bed_time)
    hours_until_bed = (bedtime_dt - now).total_seconds() / 3600

    max_safe = max_dose_for_bedtime(
        hours_until_bedtime=hours_until_bed,
        body_weight_kg=body_weight_kg,
        bedtime_threshold_mg_per_l=bedtime_threshold_mg_per_l,
        half_life_h=half_life_h,
        vd_l_per_kg=vd_l_per_kg,
        existing_residual_mg=existing_residual_mg,
    )

    target = target_dose_mg_per_kg * body_weight_kg

    # 推奨ロジック
    if hours_until_bed < cutoff_hours_before_bed:
        # 就寝が近い → カフェインは推奨しない (代替: テアニン / 短ナップ / 軽運動)
        residual_if_target = half_life_decay(
            target, hours_until_bed, half_life_h=half_life_h
        )
        conc = blood_concentration(
            target, hours_until_bed, body_weight_kg=body_weight_kg,
            half_life_h=half_life_h, vd_l_per_kg=vd_l_per_kg,
        )
        return CaffeineRecommendation(
            recommended_mg=None,
            instant_coffee_g=None,
            max_safe_mg=max_safe,
            min_cognitive_mg=min_cognitive_mg,
            hours_until_bedtime=hours_until_bed,
            bedtime_residual_if_consumed_mg=residual_if_target,
            blood_concentration_at_bedtime_mg_per_l=conc,
            half_life_h=half_life_h,
            reason=(
                f"就寝まで {hours_until_bed:.1f}h ＜ カットオフ {cutoff_hours_before_bed:.0f}h。"
                f"今飲むと就寝時血中濃度 ~{conc:.2f} mg/L で睡眠分断リスク"
            ),
        )

    if max_safe < min_cognitive_mg:
        # 認知効果の最低有効量に届かない → 推奨しない
        return CaffeineRecommendation(
            recommended_mg=None,
            instant_coffee_g=None,
            max_safe_mg=max_safe,
            min_cognitive_mg=min_cognitive_mg,
            hours_until_bedtime=hours_until_bed,
            bedtime_residual_if_consumed_mg=0.0,
            blood_concentration_at_bedtime_mg_per_l=0.0,
            half_life_h=half_life_h,
            reason=(
                f"就寝時の安全上限 {max_safe:.0f}mg ＜ 認知効果の最低有効量 {min_cognitive_mg:.0f}mg。"
                "今からは飲まずに過ごす方が ROI 高い"
            ),
        )

    recommended = min(target, max_safe)
    recommended = max(recommended, min_cognitive_mg)
    recommended = min(recommended, max_safe)  # 念のため上限再適用

    coffee_g = recommended / instant_coffee_mg_per_g
    residual = half_life_decay(recommended, hours_until_bed, half_life_h=half_life_h)
    conc = blood_concentration(
        recommended, hours_until_bed, body_weight_kg=body_weight_kg,
        half_life_h=half_life_h, vd_l_per_kg=vd_l_per_kg,
    )

    return CaffeineRecommendation(
        recommended_mg=round(recommended, 0),
        instant_coffee_g=round(coffee_g, 1),
        max_safe_mg=round(max_safe, 0),
        min_cognitive_mg=min_cognitive_mg,
        hours_until_bedtime=hours_until_bed,
        bedtime_residual_if_consumed_mg=round(residual, 1),
        blood_concentration_at_bedtime_mg_per_l=round(conc, 2),
        half_life_h=half_life_h,
        reason=_build_reason(
            recommended_mg=recommended,
            target_mg=target,
            max_safe_mg=max_safe,
            min_cog=min_cognitive_mg,
            hours_until_bed=hours_until_bed,
        ),
    )


def _build_reason(
    *,
    recommended_mg: float,
    target_mg: float,
    max_safe_mg: float,
    min_cog: float,
    hours_until_bed: float,
) -> str:
    if recommended_mg >= target_mg - 1:
        return (
            f"就寝まで {hours_until_bed:.1f}h あり、目標 {target_mg:.0f}mg (1mg/kg) を "
            "睡眠リスク内で摂取可能"
        )
    if recommended_mg <= min_cog + 1:
        return (
            f"就寝まで {hours_until_bed:.1f}h なので、睡眠を守る上限 {max_safe_mg:.0f}mg まで。"
            f"認知効果の最低有効量 {min_cog:.0f}mg で抑える"
        )
    return (
        f"就寝まで {hours_until_bed:.1f}h で安全上限 {max_safe_mg:.0f}mg。"
        f"目標 {target_mg:.0f}mg から削って提案"
    )


def predict_decay_curve(
    *,
    dose_mg: float,
    intake_time: datetime,
    bedtime: datetime,
    body_weight_kg: float,
    half_life_h: float = 5.0,
    vd_l_per_kg: float = 0.5,
    step_min: int = 30,
) -> list[dict[str, float | str]]:
    """摂取時点から bedtime までの血中濃度カーブ (30 分刻み)。"""
    if dose_mg <= 0 or bedtime <= intake_time:
        return []
    points: list[dict[str, float | str]] = []
    cur = intake_time
    while cur <= bedtime:
        h = (cur - intake_time).total_seconds() / 3600
        conc = blood_concentration(
            dose_mg, h,
            body_weight_kg=body_weight_kg,
            half_life_h=half_life_h,
            vd_l_per_kg=vd_l_per_kg,
        )
        residual = half_life_decay(dose_mg, h, half_life_h=half_life_h)
        points.append(
            {
                "time": cur.strftime("%H:%M"),
                "residual_mg": round(residual, 1),
                "concentration_mg_per_l": round(conc, 3),
            }
        )
        cur = cur + timedelta(minutes=step_min)
    return points


def _parse_hhmm(s: str) -> time:
    h, _, m = s.partition(":")
    return time(int(h), int(m))


def _next_occurrence(now: datetime, target_t: time) -> datetime:
    """now 以降の最も近い target_t を返す (timezone 維持)。"""
    today_dt = now.replace(
        hour=target_t.hour, minute=target_t.minute, second=0, microsecond=0
    )
    if today_dt <= now:
        return today_dt + timedelta(days=1)
    return today_dt

"""理想体型と現在地のギャップを「結局何をすべきか」に変換する実践プラン。

エネルギー収支とギャップから数学的に逆算し、医学的に正しい優先順位で処方する。

# 科学的前提 (医学的に正しい優先順位)
- 体重変化はエネルギー収支に従う。脂肪 1kg ≈ 7700 kcal (Wishnofsky 近似)。
  → 脂肪を減らすならカロリー収支が支配的レバー = 「食事が大半」。同じ赤字を運動で
  作るのは時間効率が悪い (分単位で提示する)。「運動しても無駄」ではなく、
  運動(筋トレ)の主目的は赤字作りではなく筋量維持・形作り。
- 筋量増加は抵抗運動 (筋トレ) が必須の刺激。タンパク質 1.6–2.2 g/kg が基質
  (Morton 2018 メタ解析)。有酸素は健康・脂肪燃焼に有効だが筋肥大の主因ではなく、
  過度だと干渉効果 (concurrent training interference) で筋肥大を阻害する。
- 同時達成 (recomposition: 脂肪減 + 筋増) は初心者・復帰者・体脂肪高めで起きやすく、
  熟練者では遅い。
- 持続可能レート: 脂肪減 体重の ~0.5–1%/週 (これ以上は除脂肪を失う)。
  筋増 中級者 ~0.25–0.5%/月 (女性は約半分; Aragon/Schoenfeld)。

# BMR / TDEE
BMR = Mifflin-St Jeor。TDEE は Garmin 実測の活動消費 (14日平均) を BMR に足す
(推定係数より実測が正確)。実測が無いときのみ活動係数 1.45 で代替。

設計: docs/superpowers/specs/2026-06-16-physique-gap-plan-design.md
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import WeightSample
from app.scoring.nutrition import (
    _bmr_mifflin,
    _garmin_active_kcal_avg,
    _hae_active_kcal_avg,
)
from app.scoring.profile import resolve_profile

KCAL_PER_KG_FAT = 7700.0  # 脂肪 1kg のエネルギー (Wishnofsky)
# シャドーボクシングの代謝当量 (MET)。中強度の連続シャドー ~7 MET。
SHADOWBOX_MET = 7.0
# 抵抗運動を主、有酸素を従に置くための既定処方
RESISTANCE_SESSIONS_PER_WEEK = 4


def _latest_body() -> tuple[float, float | None] | None:
    with session_scope() as session:
        row = session.execute(
            select(WeightSample.weight_kg, WeightSample.body_fat_pct)
            .order_by(WeightSample.ts.desc())
            .limit(1)
        ).first()
    if row is None or row[0] is None:
        return None
    return float(row[0]), (float(row[1]) if row[1] is not None else None)


def _tdee(target: date_type, bmr: float) -> tuple[float, bool]:
    """(TDEE, 実測かどうか=Falseなら推定)。Garmin/HAE 実測の活動消費を優先。"""
    with session_scope() as session:
        active = _garmin_active_kcal_avg(session, target, 14)
        if active is None:
            active = _hae_active_kcal_avg(session, target, 14)
    if active is not None and active > 0:
        return bmr + active, True
    return bmr * 1.45, False  # 実測なし → 軽度活動の係数で代替


def _kcal_per_min_shadowbox(weight_kg: float) -> float:
    # kcal/min = MET * 3.5 * kg / 200 (ACSM)
    return SHADOWBOX_MET * 3.5 * weight_kg / 200.0


def _macros(calorie_target: float, weight_kg: float, protein_g_per_kg: float) -> dict[str, Any]:
    protein_g = protein_g_per_kg * weight_kg
    protein_kcal = protein_g * 4.0
    fat_g = 0.8 * weight_kg  # 健康維持の下限 (ホルモン)
    fat_kcal = fat_g * 9.0
    carb_kcal = calorie_target - protein_kcal - fat_kcal
    if carb_kcal < 0:  # 余裕が無ければ脂肪から削る
        fat_kcal = max(0.0, calorie_target - protein_kcal)
        fat_g = fat_kcal / 9.0
        carb_kcal = max(0.0, calorie_target - protein_kcal - fat_kcal)
    return {
        "protein_g": round(protein_g),
        "protein_kcal": round(protein_kcal),
        "fat_g": round(fat_g),
        "carb_g": round(carb_kcal / 4.0),
        "protein_g_per_kg": round(protein_g_per_kg, 2),
    }


def _levers(direction: str, protein_g: int, ex_min: int) -> list[dict[str, Any]]:
    """方向別の「効果寄与のモデル優先度 (%)」。因果分解は不可能なので、
    エネルギー収支の数理 (下の diet_vs_exercise) に基づく実務優先度として提示する。"""
    if direction == "cut":
        return [
            {"name": "食事 (カロリー収支)", "share_pct": 75,
             "why": f"脂肪減は赤字次第。同じ赤字を運動で作るのは非効率 (≈{ex_min}分/日の高強度が必要)"},
            {"name": "タンパク質", "share_pct": 10,
             "why": f"減量中の筋量維持に必須 ({protein_g} g/日)"},
            {"name": "筋トレ (抵抗運動)", "share_pct": 10,
             "why": "筋量を守り、絞れた見た目を作る。脂肪だけ落とす鍵"},
            {"name": "有酸素 / シャドーボクシング", "share_pct": 5,
             "why": "赤字の補助・心肺・楽しさ(継続に効く)。主因ではない"},
        ]
    if direction == "recomp":
        return [
            {"name": "筋トレ (抵抗運動)", "share_pct": 35,
             "why": "筋肥大の必須刺激。漸進性過負荷 (progressive overload)"},
            {"name": "タンパク質", "share_pct": 30,
             "why": f"筋合成の基質 ({protein_g} g/日)。同時達成の鍵"},
            {"name": "食事 (僅かな赤字/維持)", "share_pct": 30,
             "why": "脂肪は緩やかに減らし筋は増やす絶妙な収支"},
            {"name": "有酸素 / シャドーボクシング", "share_pct": 5,
             "why": "過度は干渉効果で筋肥大を阻害。週2–3回・別日に"},
        ]
    if direction == "lean_bulk":
        return [
            {"name": "筋トレ (抵抗運動)", "share_pct": 40,
             "why": "筋肥大の必須刺激。漸進性過負荷"},
            {"name": "食事 (僅かな黒字)", "share_pct": 30,
             "why": "増量の材料。脂肪を増やしすぎない小さな黒字"},
            {"name": "タンパク質", "share_pct": 25,
             "why": f"筋合成の基質 ({protein_g} g/日)"},
            {"name": "有酸素 / シャドーボクシング", "share_pct": 5,
             "why": "心肺維持。過度は増量を相殺するので控えめ"},
        ]
    return [
        {"name": "現状維持 + 微調整", "share_pct": 60, "why": "目標に近い。質を磨く段階"},
        {"name": "タンパク質 + 筋トレ", "share_pct": 40,
         "why": f"体組成の微調整 (recomposition) を狙う ({protein_g} g/日)"},
    ]


def recomposition_plan(target: date_type) -> dict[str, Any]:
    prof = resolve_profile()
    body = _latest_body()
    if body is None:
        return {"available": False, "reason": "体重データがありません"}
    w_now, bf_now = body
    w_tgt, bf_tgt = prof.target_weight_kg, prof.target_body_fat_pct

    bmr = _bmr_mifflin(w_now, prof.height_cm, prof.age, prof.sex)
    tdee, tdee_measured = _tdee(target, bmr)

    # 体脂肪率が無いと脂肪/除脂肪量に分解できない → 体重のみのプランに縮退
    has_bf = bf_now is not None
    fm_now = w_now * bf_now / 100.0 if has_bf else None
    lm_now = w_now - fm_now if has_bf else None
    fm_tgt = w_tgt * bf_tgt / 100.0
    lm_tgt = w_tgt - fm_tgt
    d_weight = w_tgt - w_now
    d_fat = (fm_tgt - fm_now) if has_bf else None
    d_lean = (lm_tgt - lm_now) if has_bf else None

    # 方向の判定。カロリー戦略はネット体重目標を主軸にする:
    # 体重を純増させるには黒字が要る (維持では +Xkg に到達できない)、純減には赤字。
    # 体重がほぼ同じで脂肪減&筋増を狙う場合のみ「リコンプ(維持)」。
    lose_fat = (d_fat <= -0.5) if has_bf else (d_weight < 0)
    gain_lean = (d_lean >= 0.5) if has_bf else (d_weight > 0)
    if d_weight > 0.5:
        direction = "lean_bulk"  # 純増 → 小さな黒字
    elif d_weight < -0.5:
        direction = "cut"  # 純減 → 赤字
    elif has_bf and lose_fat and gain_lean:
        direction = "recomp"  # 同体重で組成だけ入れ替え → 維持
    else:
        direction = "maintain"

    label = {
        "cut": "減量 (脂肪を落とす)",
        "recomp": "リコンプ (脂肪減 + 筋増を同時に)",
        "lean_bulk": "リーンバルク (脂肪を抑えて筋を増やす)",
        "maintain": "現状維持 + 微調整",
    }[direction]

    # カロリー目標
    rate_pct = {"cut": 0.0075, "recomp": 0.005, "lean_bulk": 0.0, "maintain": 0.0}[direction]
    daily_deficit = 0.0
    if direction in ("cut", "recomp"):
        r_fat_kg_wk = rate_pct * w_now
        daily_deficit = r_fat_kg_wk * KCAL_PER_KG_FAT / 7.0
        daily_deficit = min(daily_deficit, 0.25 * tdee)  # 25% 上限 (筋量保護)
        # BMR を下回らない
        daily_deficit = min(daily_deficit, max(0.0, tdee - bmr * 1.1))
        calorie_target = tdee - daily_deficit
        delta_kcal = -round(daily_deficit)
    elif direction == "lean_bulk":
        surplus = 0.10 * tdee
        calorie_target = tdee + surplus
        delta_kcal = round(surplus)
    else:
        surplus = 0.0
        calorie_target = tdee
        delta_kcal = 0

    macros = _macros(calorie_target, w_now, prof.protein_g_per_kg)

    # 食事 vs 運動: 同じ赤字を運動で作るのに必要な時間
    kcal_min = _kcal_per_min_shadowbox(w_now)
    ex_min = round(daily_deficit / kcal_min) if daily_deficit > 0 and kcal_min > 0 else 0

    # 方向に応じた「食事の核心」メッセージ (食事が主レバーである理由を数理で)
    if daily_deficit > 0:
        dve_headline = "食事が主レバー"
        dve_note = (
            f"同じ {round(daily_deficit)} kcal の赤字を運動だけで作るには高強度シャドーボクシング "
            f"約 {ex_min} 分/日。食事で {round(daily_deficit)} kcal 減らす方が圧倒的に楽 = 食事が主レバー。"
        )
    elif delta_kcal > 0:
        dve_headline = "黒字は筋肉の材料"
        dve_note = (
            f"筋を {round(d_lean, 1) if d_lean else '+'}kg 増やすには小さな黒字 (+{delta_kcal} kcal/日) が必要。"
            "維持カロリーのままでは純増しない。ただし黒字を大きくしすぎると脂肪が増えるだけ。"
            "黒字は筋トレ刺激とセットで初めて筋になる。有酸素のやり過ぎは黒字を相殺。"
        )
    else:
        dve_headline = "現状維持 + 質"
        dve_note = "体重は目標域。赤字も黒字も不要。タンパク質と筋トレで組成の質を磨く局面。"

    levers = _levers(direction, macros["protein_g"], ex_min)

    # タイムライン (持続可能レートでの所要週数)
    weeks_fat = abs(d_fat) / (0.0075 * w_now) if (has_bf and d_fat is not None and d_fat < 0) else 0.0
    # 筋増レート: 中級 0.5%/月、女性は半分 → 週換算
    musc_month_pct = 0.005 * (0.5 if prof.sex.lower().startswith("f") else 1.0)
    r_musc_kg_wk = musc_month_pct * w_now / 4.345
    weeks_musc = (d_lean / r_musc_kg_wk) if (has_bf and d_lean is not None and d_lean > 0 and r_musc_kg_wk > 0) else 0.0
    eta_weeks = max(weeks_fat, weeks_musc)

    notes: list[str] = []
    if not tdee_measured:
        notes.append("TDEE は実測の活動消費が無いため推定値 (係数1.45)。ウォッチ装着でより正確に。")
    if not has_bf:
        notes.append("体脂肪率の記録が無いため脂肪/筋の内訳は概算。体組成計の記録で精度が上がる。")
    if direction == "recomp":
        notes.append("リコンプは筋増の速度が律速。脂肪減は早く見えても筋増はゆっくり=焦らない。")
    if weeks_musc > weeks_fat and weeks_musc > 0:
        notes.append("ボトルネックは筋増。タンパク質と漸進性過負荷を最優先に。")

    return {
        "available": True,
        "direction": direction,
        "direction_label": label,
        "current": {
            "weight_kg": round(w_now, 1),
            "body_fat_pct": round(bf_now, 1) if has_bf else None,
            "fat_mass_kg": round(fm_now, 1) if has_bf else None,
            "lean_mass_kg": round(lm_now, 1) if has_bf else None,
        },
        "target": {
            "weight_kg": round(w_tgt, 1),
            "body_fat_pct": round(bf_tgt, 1),
            "fat_mass_kg": round(fm_tgt, 1),
            "lean_mass_kg": round(lm_tgt, 1),
        },
        "gap": {
            "d_weight_kg": round(d_weight, 1),
            "d_fat_mass_kg": round(d_fat, 1) if has_bf else None,
            "d_lean_mass_kg": round(d_lean, 1) if has_bf else None,
        },
        "energy": {
            "bmr": round(bmr),
            "tdee": round(tdee),
            "tdee_measured": tdee_measured,
            "calorie_target": round(calorie_target),
            "delta_kcal": delta_kcal,
        },
        "macros": macros,
        "diet_vs_exercise": {
            "daily_deficit_kcal": round(daily_deficit),
            "shadowbox_min_equiv": ex_min,
            "headline": dve_headline,
            "note": dve_note,
        },
        "levers": levers,
        "training": {
            "resistance_sessions_per_week": RESISTANCE_SESSIONS_PER_WEEK,
            "primary": "筋トレ (抵抗運動) を主軸に。大筋群の複合種目 + 漸進性過負荷。",
            "shadowboxing": (
                "シャドーボクシングは継続OK (楽しい=adherenceに効く)。位置づけはコンディショニング・"
                "脂肪燃焼・技術であって筋量の主因ではない。"
            ),
            "interference": (
                "高強度有酸素を筋トレ直前や大量に行うと筋肥大シグナルと競合 (干渉効果)。"
                "筋トレを優先し、シャドーは別日 or 筋トレ後・週2–3回に。"
            ),
        },
        "timeline": {
            "weeks_fat": round(weeks_fat, 1),
            "weeks_muscle": round(weeks_musc, 1),
            "eta_weeks": round(eta_weeks, 1),
            "eta_label": _eta_label(eta_weeks),
        },
        "notes": notes,
    }


def _eta_label(weeks: float) -> str:
    if weeks <= 0:
        return "目標域に到達済み — 維持と質の向上へ"
    if weeks < 8:
        return f"約 {round(weeks)} 週間"
    months = weeks / 4.345
    return f"約 {months:.1f} ヶ月 ({round(weeks)} 週)"

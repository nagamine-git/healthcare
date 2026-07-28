"""目標体型との定量的なギャップ評価 (DB 非依存の純関数)。

# なぜこのモジュールが要るか
既存の周径パネル (`scoring/body_measurement.py`) は WHtR や海軍式体脂肪率を
「良好」「2本がおおむね一致」のように相対評価するだけで、**目標との距離**を
一切示していなかった。本モジュールは体重・体脂肪率だけでなく、除脂肪体重
(LBM: Lean Body Mass) のギャップを主役に据えて「結局なにが足りないのか」を
言い切る。`scoring/physique_plan.py`(実践プラン: カロリー/マクロ/トレーニング処方)
とは目的が異なり、こちらは処方箋の手前の**現状診断**に専念する。

# なぜ除脂肪体重 (LBM) を主役にするか
体重ギャップだけを見ると「痩せ型なのに体重が目標に届かない→もっと食べて増量」
という発想に流れやすい。しかし体脂肪率が既に目標付近なら、体重ギャップの正体は
脂肪ではなく除脂肪体重 (≒筋量) の不足であり、必要なのは(脂肪も増える)雑な増量
ではなく筋量そのものである。

    LBM = 体重 × (1 - 体脂肪率/100)

を現在・目標それぞれで算出し、その差分 (lbm_gap_kg) を「本当の課題」として扱う。
体脂肪率が目標から大きく離れている場合は、脂肪側のギャップ (fat_mass_gap_kg) も
判定に使う。

# 符号の向き
本モジュールの gap 系の値はすべて「現在値 − 目標値」(= 目標にどれだけ届いていないか)
で統一する。体重・LBM は負値 (マイナス) が「不足 (増やす必要)」、体脂肪率・脂肪量は
正値が「超過 (減らす必要)」を意味する。日常語の「目標比 -9.0kg」という言い回しに
素直に対応させるための設計判断。

# 筋量増加ペースの目安 (断定しない)
ナチュラルの筋量増加速度には大きな個人差があるが、トレーニング経験・年齢・遺伝で
決まり、一般に**年 2-4kg 程度が現実的な上限**とされる (初心者ほど速く、経験者ほど
遅い; Helms, Aragon & Fitschen 2014, ISSN Position Stand の定性的合意)。
`scoring/physique_plan.py` は FFMI ヘッドルームから月次で動的推定するが、本モジュールは
「現状評価」であって「実行プラン」ではないため、そこまでの精密さを狙わず速い/遅いの
両端 (年2kg〜4kg) を使った**幅のある目安**として提示する。ここは断定してはいけない
(個人差・トレーニング歴を聞かずに出す数字であるため)。

# 脂肪減の目安ペース
持続可能な脂肪減少は一般に体重の 0.5-1%/週 程度とされる (これ以上は除脂肪も
一緒に失われやすい)。`scoring/physique_plan.py` の cut レート (0.75%/週) と整合する
範囲を採用する。

設計: このタスクの spec (docs 化はしていない、PR 説明を参照)。
"""

from __future__ import annotations

from typing import Any, Literal

# --- LBM ギャップを「有意」とみなす閾値 (kg) ---
# 体重計・体脂肪率の測定誤差 (BIA ±2-4%) を体重換算すると 1kg 前後のブレが出るため、
# それ未満の LBM ギャップは「ノイズの範囲」として扱い、無理に verdict を出さない。
LBM_GAP_MEANINGFUL_KG = 1.0

# --- 体重ギャップを「目標に到達済み」とみなす閾値 (kg) ---
WEIGHT_GAP_NEAR_TARGET_KG = 1.0

# --- 筋量増加ペースの目安 (年 kg, ナチュラル) ---
MUSCLE_GAIN_RATE_LOW_KG_YR = 2.0
MUSCLE_GAIN_RATE_HIGH_KG_YR = 4.0

# --- 脂肪減少ペースの目安 (体重比 %/週) ---
FAT_LOSS_RATE_LOW_PCT_BW_WK = 0.005  # 0.5%/週 (ゆっくり・除脂肪を守りやすい)
FAT_LOSS_RATE_HIGH_PCT_BW_WK = 0.01  # 1.0%/週 (速い・上限目安)

# --- WHtR: 閾値 (0.5) からの距離がこの範囲内なら「境界線上」として明示する ---
# メジャーの当て方で数mm〜1cm程度は普通にブレる (ウエスト 80cm 前後なら
# 身長比で ±0.01 弱に相当) ため、閾値からの距離がそれと同程度以下なら
# 「良好」と言い切らず境界線上であることを見せる。
WHTR_BORDERLINE_BAND = 0.02

# --- 骨格筋率の参考レンジ (男性、目安。文献・測定方式でばらつきが大きく確定基準はない) ---
# 医療機器ではないため断定的な正常/異常判定はしない。あくまで「参考」として
# 相対位置 (レンジ内で低め/高めか) を示すだけに留める。
SKELETAL_MUSCLE_PCT_REF_LOW_MALE = 33.0
SKELETAL_MUSCLE_PCT_REF_MID_MALE = 38.0
SKELETAL_MUSCLE_PCT_REF_HIGH_MALE = 45.0

# --- 内臓脂肪レベル: 体組成計(Tanita/Omron 系)で一般的に使われる「標準」上限 ---
# フロントの BodyCompositionPanel.tsx で既に同じ閾値 (>=10 で警戒色) を使っており、
# ここでも同じ基準に揃える (アプリ内で一貫させる)。
VISCERAL_FAT_STANDARD_MAX = 10.0

Direction = Literal["cut", "recomp", "gain_lean", "maintain", "fine_tune"]


def weight_gap(weight_kg: float, target_weight_kg: float) -> dict[str, Any]:
    """体重ギャップ (現在 − 目標)。負値 = 目標に届いていない (不足)。"""
    gap_kg = weight_kg - target_weight_kg
    gap_pct = (gap_kg / target_weight_kg * 100.0) if target_weight_kg else 0.0
    return {
        "now_kg": round(weight_kg, 1),
        "target_kg": round(target_weight_kg, 1),
        "gap_kg": round(gap_kg, 1),
        "gap_pct": round(gap_pct, 1),
        "near_target": abs(gap_kg) <= WEIGHT_GAP_NEAR_TARGET_KG,
    }


def body_fat_gap(
    body_fat_pct: float,
    target_body_fat_pct: float,
    tolerance_pct: float,
    *,
    secondary_pct: float | None = None,
) -> dict[str, Any]:
    """体脂肪率ギャップ (現在 − 目標)。正値 = 目標より高い (超過)。

    プロファイルの body_fat_tolerance_pct (個人設定の許容幅) を「ほぼ達成」の
    判定に使う。周径ベースの海軍式 (secondary_pct) があれば併記し、どちらも
    許容幅内なら「両方の推定で目標達成」と言い切れる。
    """
    gap_pt = body_fat_pct - target_body_fat_pct
    near_target = abs(gap_pt) <= tolerance_pct
    secondary_gap_pt = (secondary_pct - target_body_fat_pct) if secondary_pct is not None else None
    secondary_near_target = (
        abs(secondary_gap_pt) <= tolerance_pct if secondary_gap_pt is not None else None
    )
    return {
        "now_pct": round(body_fat_pct, 1),
        "secondary_pct": round(secondary_pct, 1) if secondary_pct is not None else None,
        "target_pct": round(target_body_fat_pct, 1),
        "tolerance_pct": round(tolerance_pct, 1),
        "gap_pt": round(gap_pt, 1),
        "near_target": near_target,
        "secondary_near_target": secondary_near_target,
        # 両方の推定が許容幅内 (無ければ片方のみで判定)
        "confirmed_near_target": near_target and (secondary_near_target is not False),
    }


def lbm_gap(
    weight_kg: float,
    body_fat_pct: float,
    target_weight_kg: float,
    target_body_fat_pct: float,
) -> dict[str, Any]:
    """除脂肪体重 (LBM) のギャップ。負値 = 目標より不足 (増やす必要)。

    ここが本モジュールの核。体重ギャップが同じでも、その中身が脂肪不足なのか
    筋量不足なのかで処方はまったく変わる。
    """
    lbm_now = weight_kg * (1.0 - body_fat_pct / 100.0)
    lbm_target = target_weight_kg * (1.0 - target_body_fat_pct / 100.0)
    gap_kg = lbm_now - lbm_target
    gap_pct = (gap_kg / lbm_target * 100.0) if lbm_target else 0.0
    fat_now = weight_kg - lbm_now
    fat_target = target_weight_kg - lbm_target
    fat_gap_kg = fat_now - fat_target
    return {
        "now_kg": round(lbm_now, 1),
        "target_kg": round(lbm_target, 1),
        "gap_kg": round(gap_kg, 1),
        "gap_pct": round(gap_pct, 1),
        "meaningful": abs(gap_kg) >= LBM_GAP_MEANINGFUL_KG,
        "fat_mass_now_kg": round(fat_now, 1),
        "fat_mass_target_kg": round(fat_target, 1),
        "fat_mass_gap_kg": round(fat_gap_kg, 1),
    }


def determine_verdict(
    *,
    weight_gap_kg: float,
    bf_gap_pt: float,
    bf_tolerance_pt: float,
    lbm_gap_kg: float,
) -> dict[str, Any]:
    """何が課題かを言い切る verdict。

    優先順位:
    1. 体脂肪が許容幅を超えて多く、かつ除脂肪も不足 → リコンプ (同時対応)
    2. 体脂肪が許容幅を超えて多いだけ → 減量
    3. 体脂肪はほぼ目標、除脂肪が不足 → 筋量が必要 (このタスクの主眼のケース)
    4. すべて許容幅内 → 維持でよい
    5. それ以外 (中途半端なズレ) → 微調整
    """
    bf_excess = bf_gap_pt > bf_tolerance_pt  # 目標より脂肪が多い
    bf_ok = abs(bf_gap_pt) <= bf_tolerance_pt
    lbm_deficit = lbm_gap_kg <= -LBM_GAP_MEANINGFUL_KG
    lbm_excess = lbm_gap_kg >= LBM_GAP_MEANINGFUL_KG
    weight_ok = abs(weight_gap_kg) <= WEIGHT_GAP_NEAR_TARGET_KG

    if bf_excess and lbm_deficit:
        code: Direction = "recomp"
        label = "リコンプが必要 (脂肪を減らしながら筋量を増やす)"
        explanation = (
            f"体脂肪率が目標より {bf_gap_pt:.1f}pt 高く、除脂肪体重は "
            f"{abs(lbm_gap_kg):.1f}kg 不足。増量だけでも減量だけでも届かず、両方を同時に動かす必要がある。"
            "ただし同時達成 (リコンポジション) は、片方に絞って取り組むより進みが緩やかになるのが一般的"
            "(体脂肪の高さ・トレーニング再開直後の初心者ボーナスがあるほど起きやすく、熟練者ほど遅い)。"
        )
    elif bf_excess:
        code = "cut"
        label = "減量が必要"
        explanation = f"体脂肪率が目標より {bf_gap_pt:.1f}pt 高い。除脂肪体重はほぼ目標域。"
    elif bf_ok and lbm_deficit:
        code = "gain_lean"
        label = "筋量が必要"
        explanation = (
            f"体脂肪率はほぼ目標 (差 {bf_gap_pt:+.1f}pt、許容 ±{bf_tolerance_pt:.1f}pt)。"
            f"一方で除脂肪体重が目標より {abs(lbm_gap_kg):.1f}kg 少ない。"
            "体重ギャップの正体は脂肪不足ではなく筋量不足であり、減量ではなく筋量を増やす方向が妥当。"
        )
    elif bf_ok and weight_ok and not lbm_deficit and not lbm_excess:
        code = "maintain"
        label = "維持でよい"
        explanation = "体重・体脂肪率・除脂肪体重のいずれも目標域。質を保つ段階。"
    elif bf_ok and lbm_excess:
        code = "maintain"
        label = "維持でよい (既に目標水準)"
        explanation = "体脂肪率は目標域で、除脂肪体重は目標を上回る。無理に増減させる必要はない。"
    else:
        code = "fine_tune"
        label = "微調整でよい"
        explanation = "大きなギャップはないが、体重・体脂肪率・除脂肪体重のいずれかに小さなズレが残る。"

    return {"code": code, "label": label, "explanation": explanation}


def estimate_timeframe(
    *,
    direction: str,
    lbm_gap_kg: float,
    fat_mass_gap_kg: float,
    weight_kg: float,
) -> dict[str, Any] | None:
    """課題の解消に要する期間の目安。「あと少し」という誤解を避けるための数字。

    断定はできない (個人差・トレーニング歴・遺伝が大きく効くため) ので、
    速い/遅いケースの両端を出して「幅」で見せる。maintain/fine_tune では None。
    """
    lean_needed = max(0.0, -lbm_gap_kg)  # 不足分 (kg)
    fat_needed = max(0.0, fat_mass_gap_kg)  # 超過分 (kg)

    lean_years: tuple[float, float] | None = None
    if lean_needed > 0:
        lean_years = (
            lean_needed / MUSCLE_GAIN_RATE_HIGH_KG_YR,  # 速いケース → 短い方
            lean_needed / MUSCLE_GAIN_RATE_LOW_KG_YR,  # 遅いケース → 長い方
        )

    fat_weeks: tuple[float, float] | None = None
    if fat_needed > 0 and weight_kg > 0:
        fat_weeks = (
            fat_needed / (FAT_LOSS_RATE_HIGH_PCT_BW_WK * weight_kg),  # 速いケース
            fat_needed / (FAT_LOSS_RATE_LOW_PCT_BW_WK * weight_kg),  # 遅いケース
        )

    if lean_years is None and fat_weeks is None:
        return None

    # 筋量増加はナチュラルの生物学的上限が効くボトルネックになりやすいので、
    # 両方必要なリコンプでは筋量側の期間を主役の目安にする (physique_plan.py の
    # eta = max(weeks_fat, weeks_musc) という「遅い方が律速」という考え方と同じ)。
    if lean_years is not None:
        lo, hi = lean_years
        basis = (
            "ナチュラルの筋量増加は年2-4kg程度が現実的な上限という一般的な目安"
            "(個人差・トレーニング歴で大きく変わるため断定はできない)。"
        )
        if fat_weeks is not None:
            if direction == "recomp":
                # 同時達成(リコンポジション)は脂肪減・筋増のどちらも片方に絞るより
                # 緩やかに進むのが一般的 (physique_plan.py の docstring と同じ前提)。
                # 「脂肪は先に片付く」と言い切らない。
                basis += (
                    " 脂肪減と筋量増を同時に進めるため、どちらも片方に絞る場合より緩やかになりやすい"
                    "(この目安の年数はさらに伸びる可能性がある)。"
                )
            else:
                basis += " 脂肪側は数ヶ月〜半年程度で解消できる見込み。"
        # 1年未満の小さなギャップは月単位で見せた方が直感的、それ以上は年単位。
        if hi < 1.0:
            label = f"目安 約{lo * 12:.0f}〜{hi * 12:.0f}ヶ月"
        else:
            label = f"目安 約{lo:.1f}〜{hi:.1f}年 (年単位の課題。あと少しではない)"
        return {
            "kind": "lean_gain",
            "years_low": round(lo, 1),
            "years_high": round(hi, 1),
            "label": label,
            "basis": basis,
        }

    assert fat_weeks is not None
    lo_w, hi_w = fat_weeks
    return {
        "kind": "fat_loss",
        "weeks_low": round(lo_w, 1),
        "weeks_high": round(hi_w, 1),
        "label": f"目安 約{lo_w:.0f}〜{hi_w:.0f}週",
        "basis": "持続可能な脂肪減少は体重の0.5-1%/週程度という一般的な目安(除脂肪を守れる範囲)。",
    }


def whtr_assessment(ratio: float | None, status: str | None) -> dict[str, Any] | None:
    """WHtR の境界値扱い。閾値 (0.5) に近いほど「境界線上」であることを明示する。

    既存の whtr_status() は good/caution/high の3値だけで、0.499 のような
    「閾値のすぐ内側」を "good" と言い切ってしまい、重要な情報が落ちる。
    ここでは status はそのまま使いつつ、borderline フラグで補う。
    """
    if ratio is None or status is None:
        return None
    distance = abs(ratio - 0.5)
    borderline = distance <= WHTR_BORDERLINE_BAND
    if borderline:
        note = (
            f"WHtR {ratio:.3f} は閾値 0.5 のすぐ近く (境界線上)。"
            "メジャーの当て方で数mm変わればどちら側にも転ぶ差なので、"
            "「良好」と言い切らず経過観察の対象として見る。"
        )
    elif status == "good":
        note = f"WHtR {ratio:.3f} は閾値 0.5 から十分離れており、明確に良好。"
    elif status == "caution":
        note = f"WHtR {ratio:.3f} は要注意帯 (0.5-0.6)。"
    else:
        note = f"WHtR {ratio:.3f} は高リスク帯 (0.6以上)。"
    return {"ratio": ratio, "status": status, "borderline": borderline, "note": note}


def skeletal_muscle_reference(pct: float | None, sex: str | None) -> dict[str, Any] | None:
    """骨格筋率の参考レンジとの相対位置。診断ではなく参考情報として。

    文献・測定方式 (BIA の電極配置やアルゴリズム) でばらつきが大きく、確立された
    正常/異常の基準値は無いため、断定的な判定はしない。あくまで目安レンジ内での
    相対位置 (低め/中間/高め) を示すだけに留める。女性は参考レンジ未整備のため None。
    """
    if pct is None or sex is None or not sex.strip().lower().startswith("m"):
        return None
    if pct < SKELETAL_MUSCLE_PCT_REF_LOW_MALE:
        band = "below_reference"
        note = (
            f"骨格筋率 {pct:.1f}% は、成人男性でよく参照される目安レンジ "
            f"(概ね{SKELETAL_MUSCLE_PCT_REF_LOW_MALE:.0f}-{SKELETAL_MUSCLE_PCT_REF_HIGH_MALE:.0f}%、"
            "文献・測定方式でばらつき大) の下限を下回る。診断的な意味はなく参考情報。"
        )
    elif pct < SKELETAL_MUSCLE_PCT_REF_MID_MALE:
        band = "within_reference_low"
        note = (
            f"骨格筋率 {pct:.1f}% は参考レンジ内だが低めの側。確立した正常値は無いため参考情報。"
        )
    elif pct <= SKELETAL_MUSCLE_PCT_REF_HIGH_MALE:
        band = "within_reference_high"
        note = f"骨格筋率 {pct:.1f}% は参考レンジ内で高めの側。"
    else:
        band = "above_reference"
        note = f"骨格筋率 {pct:.1f}% は参考レンジの上限を上回る (高強度トレーニング歴などで見られる)。"
    return {
        "pct": round(pct, 1),
        "band": band,
        "reference_low": SKELETAL_MUSCLE_PCT_REF_LOW_MALE,
        "reference_high": SKELETAL_MUSCLE_PCT_REF_HIGH_MALE,
        "note": note,
    }


def visceral_fat_reference(level: float | None) -> dict[str, Any] | None:
    """内臓脂肪レベルの参考評価。フロント (BodyCompositionPanel.tsx) と同じ閾値 (10) に揃える。"""
    if level is None:
        return None
    status = "standard" if level < VISCERAL_FAT_STANDARD_MAX else "elevated"
    note = (
        f"内臓脂肪レベル {level:g} は、一般に{VISCERAL_FAT_STANDARD_MAX:.0f}未満が標準の目安とされる範囲内。"
        if status == "standard"
        else f"内臓脂肪レベル {level:g} は、一般的な標準の目安 ({VISCERAL_FAT_STANDARD_MAX:.0f}未満) を上回る。"
    )
    return {"level": level, "status": status, "note": note}


def assess_physique_gap(
    *,
    weight_kg: float | None,
    body_fat_pct: float | None,
    target_weight_kg: float,
    target_body_fat_pct: float,
    body_fat_tolerance_pct: float,
    height_cm: float | None = None,
    sex: str | None = None,
    body_fat_pct_secondary: float | None = None,
    waist_cm: float | None = None,
    whtr_ratio: float | None = None,
    whtr_status_value: str | None = None,
    skeletal_muscle_pct: float | None = None,
    visceral_fat_level: float | None = None,
) -> dict[str, Any]:
    """目標とのギャップを一括評価するエントリポイント。

    体重・体脂肪率が無いと LBM に分解できないため available=False を返す
    (`scoring/physique_plan.py` と同じ縮退方針)。
    """
    if weight_kg is None or body_fat_pct is None:
        return {"available": False, "reason": "体重・体脂肪率のデータがありません"}

    w_gap = weight_gap(weight_kg, target_weight_kg)
    bf_gap = body_fat_gap(
        body_fat_pct, target_body_fat_pct, body_fat_tolerance_pct,
        secondary_pct=body_fat_pct_secondary,
    )
    l_gap = lbm_gap(weight_kg, body_fat_pct, target_weight_kg, target_body_fat_pct)

    verdict = determine_verdict(
        weight_gap_kg=w_gap["gap_kg"],
        bf_gap_pt=bf_gap["gap_pt"],
        bf_tolerance_pt=body_fat_tolerance_pct,
        lbm_gap_kg=l_gap["gap_kg"],
    )
    timeframe = estimate_timeframe(
        direction=verdict["code"],
        lbm_gap_kg=l_gap["gap_kg"],
        fat_mass_gap_kg=l_gap["fat_mass_gap_kg"],
        weight_kg=weight_kg,
    )

    return {
        "available": True,
        "weight": w_gap,
        "body_fat": bf_gap,
        "lbm": l_gap,
        "verdict": verdict,
        "timeframe": timeframe,
        "secondary": {
            "whtr": whtr_assessment(whtr_ratio, whtr_status_value),
            "skeletal_muscle": skeletal_muscle_reference(skeletal_muscle_pct, sex),
            "visceral_fat": visceral_fat_reference(visceral_fat_level),
        },
    }

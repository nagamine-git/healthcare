from __future__ import annotations

import pytest

from app.scoring.body_measurement import whtr, whtr_status
from app.scoring.physique_gap import (
    assess_physique_gap,
    body_fat_gap,
    determine_verdict,
    estimate_timeframe,
    lbm_gap,
    skeletal_muscle_reference,
    visceral_fat_reference,
    weight_gap,
    whtr_assessment,
)

# ----- 実データ (実測値) -----
# 身長166.2cm/体重56.0kg/BMI20.3、体脂肪率 BIA17.7%・海軍式19.4%、
# ウエスト83cm/首35cm、骨格筋率34.2%、内臓脂肪4lv。
#
# 目標値は resolve_profile() (= UserProfile 設定画面で保存された値) が正。
# config.py の既定値 (65.0kg/18.0%) ではなく、実際に設定画面で保存されている
# 60.0kg/12.0% を使う (config の既定値をそのまま使うと、ユーザーが設定画面で
# 変えた値を無視してしまう)。
HEIGHT_CM = 166.2
WEIGHT_KG = 56.0
BF_BIA = 17.7
BF_NAVY = 19.4
WAIST_CM = 83.0
TARGET_WEIGHT_KG = 60.0
TARGET_BF_PCT = 12.0
TOLERANCE_PCT = 1.5
SKELETAL_MUSCLE_PCT = 34.2
VISCERAL_FAT_LEVEL = 4.0


# ----- weight_gap -----


def test_weight_gap_deficit_is_negative():
    g = weight_gap(WEIGHT_KG, TARGET_WEIGHT_KG)
    # 56.0 - 60.0 = -4.0
    assert g["gap_kg"] == -4.0
    assert g["near_target"] is False


def test_weight_gap_within_tolerance_is_near_target():
    g = weight_gap(64.5, 65.0)
    assert g["near_target"] is True


# ----- body_fat_gap -----


def test_body_fat_gap_excess_with_ambitious_target():
    # 目標体脂肪12%はかなり絞った値なので、現状(17.7/19.4%)は許容幅を超えて超過側
    g = body_fat_gap(BF_BIA, TARGET_BF_PCT, TOLERANCE_PCT, secondary_pct=BF_NAVY)
    assert g["gap_pt"] == pytest.approx(5.7, abs=0.01)
    assert g["near_target"] is False
    assert g["secondary_near_target"] is False
    assert g["confirmed_near_target"] is False


def test_body_fat_gap_excess_beyond_tolerance():
    g = body_fat_gap(25.0, 18.0, 1.5)
    assert g["gap_pt"] == 7.0
    assert g["near_target"] is False


def test_body_fat_gap_near_target_within_tolerance():
    g = body_fat_gap(17.7, 18.0, 1.5, secondary_pct=19.4)
    assert g["gap_pt"] == -0.3
    assert g["near_target"] is True
    assert g["secondary_near_target"] is True
    assert g["confirmed_near_target"] is True


# ----- lbm_gap: 本モジュールの核心 -----


def test_lbm_gap_matches_hand_calculation():
    g = lbm_gap(WEIGHT_KG, BF_BIA, TARGET_WEIGHT_KG, TARGET_BF_PCT)
    # 56 * (1 - 0.177) = 46.088 -> 46.1
    assert g["now_kg"] == pytest.approx(46.1, abs=0.05)
    # 60 * (1 - 0.12) = 52.8
    assert g["target_kg"] == pytest.approx(52.8, abs=0.05)
    # 46.088 - 52.8 = -6.712 -> 約-6.7kg (除脂肪が6.7kg不足)
    assert g["gap_kg"] == pytest.approx(-6.7, abs=0.05)
    assert g["meaningful"] is True
    # 脂肪量側: 現在9.9kg・目標7.2kg → 2.7kg 超過
    assert g["fat_mass_now_kg"] == pytest.approx(9.9, abs=0.05)
    assert g["fat_mass_target_kg"] == pytest.approx(7.2, abs=0.05)
    assert g["fat_mass_gap_kg"] == pytest.approx(2.7, abs=0.05)


def test_lbm_gap_small_difference_not_meaningful():
    # ほぼ同じ組成なら「有意なギャップ」にならない
    g = lbm_gap(65.0, 18.0, 65.0, 18.0)
    assert g["meaningful"] is False


# ----- determine_verdict -----


def test_verdict_gain_lean_when_bodyfat_ok_but_lean_deficit():
    v = determine_verdict(weight_gap_kg=-9.0, bf_gap_pt=-0.3, bf_tolerance_pt=1.5, lbm_gap_kg=-7.2)
    assert v["code"] == "gain_lean"
    assert v["label"] == "筋量が必要"


def test_verdict_cut_when_bodyfat_excess_and_lean_ok():
    v = determine_verdict(weight_gap_kg=5.0, bf_gap_pt=6.0, bf_tolerance_pt=1.5, lbm_gap_kg=0.0)
    assert v["code"] == "cut"
    assert v["label"] == "減量が必要"


def test_verdict_recomp_when_bodyfat_excess_and_lean_deficit():
    v = determine_verdict(weight_gap_kg=0.0, bf_gap_pt=6.0, bf_tolerance_pt=1.5, lbm_gap_kg=-3.0)
    assert v["code"] == "recomp"
    # 「筋量が必要」だけだと脂肪超過が落ちるので、単独の verdict と区別できる文言にする
    assert "リコンプ" in v["label"]
    assert "減量" in v["explanation"] or "脂肪" in v["explanation"]


def test_verdict_recomp_with_real_data_mentions_both_fat_and_lean():
    # 実データ (体脂肪超過 + 除脂肪不足) は recomp になり、
    # 「筋量が必要」だけでは脂肪超過(-2.7kg必要)が説明から落ちてしまう。
    v = determine_verdict(weight_gap_kg=-4.0, bf_gap_pt=5.7, bf_tolerance_pt=1.5, lbm_gap_kg=-6.7)
    assert v["code"] == "recomp"
    assert v["label"] != "筋量が必要"  # 片方だけの言い切りにしない


def test_verdict_maintain_when_all_within_tolerance():
    v = determine_verdict(weight_gap_kg=0.2, bf_gap_pt=0.1, bf_tolerance_pt=1.5, lbm_gap_kg=0.1)
    assert v["code"] == "maintain"


# ----- estimate_timeframe: 「あと少し」ではないことを示す -----


def test_timeframe_lean_gain_is_year_scale_not_weeks():
    t = estimate_timeframe(direction="gain_lean", lbm_gap_kg=-7.2, fat_mass_gap_kg=-1.8, weight_kg=WEIGHT_KG)
    assert t is not None
    assert t["kind"] == "lean_gain"
    # 7.2kg ÷ (年4kg〜年2kg) = 1.8〜3.6年
    assert t["years_low"] == pytest.approx(1.8, abs=0.05)
    assert t["years_high"] == pytest.approx(3.6, abs=0.05)
    assert "年" in t["label"]


def test_timeframe_recomp_notes_slower_than_sequential():
    # 実データ相当: 除脂肪 -6.7kg 不足・脂肪 +2.7kg 超過 の同時対応(リコンプ)
    t = estimate_timeframe(direction="recomp", lbm_gap_kg=-6.7, fat_mass_gap_kg=2.7, weight_kg=WEIGHT_KG)
    assert t is not None
    assert t["kind"] == "lean_gain"
    # 6.7kg ÷ (年4kg〜年2kg) = 1.675〜3.35年 ≒ 1.7〜3.4年
    assert t["years_low"] == pytest.approx(1.7, abs=0.1)
    assert t["years_high"] == pytest.approx(3.4, abs=0.1)
    # 「脂肪は先に片付く」と言い切らず、同時進行は緩やかになる旨が根拠に含まれること
    assert "緩やか" in t["basis"] or "同時" in t["basis"]


def test_timeframe_none_when_no_gap():
    t = estimate_timeframe(direction="maintain", lbm_gap_kg=0.0, fat_mass_gap_kg=0.0, weight_kg=65.0)
    assert t is None


def test_timeframe_fat_loss_is_weeks_scale():
    t = estimate_timeframe(direction="cut", lbm_gap_kg=0.0, fat_mass_gap_kg=3.0, weight_kg=70.0)
    assert t is not None
    assert t["kind"] == "fat_loss"
    assert t["weeks_low"] > 0
    assert t["weeks_high"] >= t["weeks_low"]


# ----- whtr_assessment: 境界値の扱い -----


def test_whtr_borderline_not_silently_good():
    ratio = whtr(WAIST_CM, HEIGHT_CM)
    status = whtr_status(ratio)
    assert ratio == pytest.approx(0.499, abs=0.001)
    assert status == "good"  # 既存のロジックは good のまま (後方互換)
    a = whtr_assessment(ratio, status)
    assert a is not None
    # だが、閾値0.5のすぐ近くであることは borderline フラグで拾えていること
    assert a["borderline"] is True


def test_whtr_clearly_good_not_borderline():
    ratio = whtr(70.0, 175.0)  # 0.4 前後、十分に閾値から離れている
    status = whtr_status(ratio)
    a = whtr_assessment(ratio, status)
    assert a is not None
    assert a["borderline"] is False


def test_whtr_assessment_none_when_missing():
    assert whtr_assessment(None, None) is None


# ----- skeletal_muscle_reference: 断定しない参考情報 -----


def test_skeletal_muscle_reference_low_side_not_abnormal():
    r = skeletal_muscle_reference(SKELETAL_MUSCLE_PCT, "male")
    assert r is not None
    assert r["band"] == "within_reference_low"
    # 「異常」「低すぎる」など断定的な語を使っていないこと
    assert "異常" not in r["note"]


def test_skeletal_muscle_reference_none_for_female_or_missing():
    assert skeletal_muscle_reference(30.0, "female") is None
    assert skeletal_muscle_reference(None, "male") is None


# ----- visceral_fat_reference -----


def test_visceral_fat_standard_within_common_threshold():
    r = visceral_fat_reference(VISCERAL_FAT_LEVEL)
    assert r is not None
    assert r["status"] == "standard"


def test_visceral_fat_elevated_above_threshold():
    r = visceral_fat_reference(12.0)
    assert r is not None
    assert r["status"] == "elevated"


# ----- assess_physique_gap: エンドツーエンド (実データ、実際の目標値) -----


def test_assess_physique_gap_real_data_verdict_is_recomp():
    """体重56.0kg/BIA体脂肪17.7%/海軍式19.4% に対し、目標が体重60.0kg/体脂肪12.0%
    (resolve_profile() の実際の設定値) の場合、体脂肪率も目標より高く除脂肪体重も
    不足しているため、「筋量が必要」だけでは片手落ちで verdict は recomp になるべき。
    """
    ratio = whtr(WAIST_CM, HEIGHT_CM)
    status = whtr_status(ratio)
    result = assess_physique_gap(
        weight_kg=WEIGHT_KG,
        body_fat_pct=BF_BIA,
        target_weight_kg=TARGET_WEIGHT_KG,
        target_body_fat_pct=TARGET_BF_PCT,
        body_fat_tolerance_pct=TOLERANCE_PCT,
        height_cm=HEIGHT_CM,
        sex="male",
        body_fat_pct_secondary=BF_NAVY,
        waist_cm=WAIST_CM,
        whtr_ratio=ratio,
        whtr_status_value=status,
        skeletal_muscle_pct=SKELETAL_MUSCLE_PCT,
        visceral_fat_level=VISCERAL_FAT_LEVEL,
    )

    assert result["available"] is True
    assert result["verdict"]["code"] == "recomp"
    assert result["verdict"]["label"] != "筋量が必要"  # 脂肪超過(-2.7kg必要)を落とさない

    assert result["weight"]["gap_kg"] == -4.0
    assert result["body_fat"]["confirmed_near_target"] is False
    assert result["lbm"]["gap_kg"] == pytest.approx(-6.7, abs=0.05)
    assert result["lbm"]["fat_mass_gap_kg"] == pytest.approx(2.7, abs=0.05)

    assert result["timeframe"]["kind"] == "lean_gain"
    assert result["timeframe"]["years_low"] == pytest.approx(1.7, abs=0.1)
    assert result["timeframe"]["years_high"] == pytest.approx(3.4, abs=0.1)

    assert result["secondary"]["whtr"]["borderline"] is True
    assert result["secondary"]["skeletal_muscle"]["band"] == "within_reference_low"
    assert result["secondary"]["visceral_fat"]["status"] == "standard"


def test_assess_physique_gap_unavailable_without_weight():
    result = assess_physique_gap(
        weight_kg=None,
        body_fat_pct=None,
        target_weight_kg=65.0,
        target_body_fat_pct=18.0,
        body_fat_tolerance_pct=1.5,
    )
    assert result["available"] is False

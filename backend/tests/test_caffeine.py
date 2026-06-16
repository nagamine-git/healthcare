from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.scoring.caffeine import (
    DEFAULT_ABSORPTION_HALF_LIFE_H,
    absorption_factor,
    amount_in_body,
    blood_concentration,
    half_life_decay,
    max_dose_for_bedtime,
    predict_decay_curve,
    recommend_caffeine,
)

JST = ZoneInfo("Asia/Tokyo")


# ----- 基礎モデル -----


def test_half_life_decay_at_t_half_is_half():
    # 100mg を半減期分 (5h) 経過 → 50mg
    assert half_life_decay(100, 5.0, half_life_h=5.0) == pytest.approx(50.0, abs=0.1)


def test_half_life_decay_at_zero_is_full():
    assert half_life_decay(100, 0, half_life_h=5.0) == 100.0


def test_half_life_decay_negative_dose():
    assert half_life_decay(0, 1) == 0.0


def test_blood_concentration_zero_at_intake():
    # 1次吸収モデル: t=0 ではまだ血中に移行しておらず濃度 0
    c = blood_concentration(100, 0, body_weight_kg=56, vd_l_per_kg=0.5)
    assert c == pytest.approx(0.0, abs=1e-9)


def test_blood_concentration_rises_to_peak_then_falls():
    # tmax≈45min 付近で頂値、その後減衰 (即時吸収近似のような t=0 頂値ではない)
    cs = [blood_concentration(100, h, body_weight_kg=56) for h in (0.0, 0.25, 0.75, 2.0, 5.0)]
    assert cs[0] < cs[1] < cs[2]  # 立ち上がり相
    assert cs[2] > cs[3] > cs[4]  # 減衰相


def test_blood_concentration_terminal_matches_amplified_decay():
    # 吸収完了後 (終末相) は (D/Vd)·factor·exp(-ke*t) に収束する
    t = 6.0
    c = blood_concentration(100, t, body_weight_kg=56, half_life_h=5.0)
    factor = absorption_factor(5.0, DEFAULT_ABSORPTION_HALF_LIFE_H)
    expected = (100 / 28) * factor * math.exp(-math.log(2) * t / 5.0)
    assert c == pytest.approx(expected, rel=1e-3)


def test_blood_concentration_halves_over_half_life_in_terminal():
    # 終末相では消失半減期ぶんで半分になる
    c_a = blood_concentration(100, 6, body_weight_kg=56, half_life_h=5.0)
    c_b = blood_concentration(100, 11, body_weight_kg=56, half_life_h=5.0)
    assert c_b == pytest.approx(c_a / 2, rel=1e-3)


def test_amount_in_body_falls_back_to_instantaneous_when_no_absorption():
    # absorption_half_life_h=None → 即時吸収 (純消失) に縮退
    assert amount_in_body(
        100, 5.0, half_life_h=5.0, absorption_half_life_h=None
    ) == pytest.approx(50.0, abs=0.1)


def test_absorption_factor_is_small_amplification():
    # 既定パラメータ (5h / 0.14h) では ~1.03 倍
    factor = absorption_factor(5.0, DEFAULT_ABSORPTION_HALF_LIFE_H)
    assert 1.0 < factor < 1.06


# ----- 最大安全量 -----


def test_max_dose_zero_when_no_time_left():
    assert max_dose_for_bedtime(hours_until_bedtime=0, body_weight_kg=56) == 0.0


def test_max_dose_scales_with_remaining_time():
    # 2 倍の時間 → e^(2*ln2/5) ≈ 1.32 倍の摂取が許容される
    d_short = max_dose_for_bedtime(hours_until_bedtime=2, body_weight_kg=56)
    d_long = max_dose_for_bedtime(hours_until_bedtime=8, body_weight_kg=56)
    assert d_long > d_short


def test_max_dose_subtracts_existing_residual():
    # 既存残量 E は吸収済み (factor 補正不要) なので、新規許容量は (許容-E)/factor だけ減る
    base = max_dose_for_bedtime(hours_until_bedtime=4, body_weight_kg=56)
    with_residual = max_dose_for_bedtime(
        hours_until_bedtime=4, body_weight_kg=56, existing_residual_mg=20
    )
    factor = absorption_factor(5.0, DEFAULT_ABSORPTION_HALF_LIFE_H)
    assert base - with_residual == pytest.approx(20 / factor, abs=0.1)


# ----- 推奨ロジック -----


def test_recommend_morning_returns_target():
    # 朝 9:00、就寝 22:30 → 13.5h 余裕
    now = datetime(2026, 5, 19, 9, 0, tzinfo=JST)
    rec = recommend_caffeine(
        now=now,
        bedtime_jst_hhmm="22:30",
        body_weight_kg=56,
        target_dose_mg_per_kg=1.0,
    )
    assert rec.recommended_mg is not None
    # 1mg/kg = 56mg のターゲットが取れるはず
    assert 50 <= rec.recommended_mg <= 60
    assert rec.instant_coffee_g is not None
    assert 0.8 <= rec.instant_coffee_g <= 1.1  # 約 1g
    assert rec.blood_concentration_at_bedtime_mg_per_l < 0.5


def test_recommend_close_to_bedtime_is_blocked():
    # 21:00 で就寝 22:30 → 1.5h 余裕、カットオフ 6h 未満
    now = datetime(2026, 5, 19, 21, 0, tzinfo=JST)
    rec = recommend_caffeine(
        now=now,
        bedtime_jst_hhmm="22:30",
        body_weight_kg=56,
        cutoff_hours_before_bed=6.0,
    )
    assert rec.recommended_mg is None
    assert rec.instant_coffee_g is None
    assert "カットオフ" in rec.reason


def test_recommend_caps_when_below_cognitive_min():
    # ぎりぎり 6h で許容量が認知最低量を下回る場合
    # 30kg 軽量の極端ケース
    now = datetime(2026, 5, 19, 16, 30, tzinfo=JST)
    rec = recommend_caffeine(
        now=now,
        bedtime_jst_hhmm="22:30",  # 6h ちょうど
        body_weight_kg=30,
        min_cognitive_mg=80.0,  # 高めの最低有効量で blocked を発生させる
        cutoff_hours_before_bed=5.5,
    )
    # max_safe が 80 未満なら None になる
    if rec.max_safe_mg < 80:
        assert rec.recommended_mg is None
        assert "認知効果" in rec.reason


def test_recommend_concentration_below_threshold():
    """推奨量を飲んでも就寝時血中濃度は 0.5 mg/L 未満。"""
    now = datetime(2026, 5, 19, 10, 0, tzinfo=JST)
    rec = recommend_caffeine(
        now=now,
        bedtime_jst_hhmm="22:30",
        body_weight_kg=56,
        bedtime_threshold_mg_per_l=0.5,
    )
    assert rec.recommended_mg is not None
    assert rec.blood_concentration_at_bedtime_mg_per_l <= 0.5 + 1e-6


def test_recommend_instant_coffee_g_uses_setting():
    now = datetime(2026, 5, 19, 9, 0, tzinfo=JST)
    rec = recommend_caffeine(
        now=now,
        bedtime_jst_hhmm="22:30",
        body_weight_kg=56,
        instant_coffee_mg_per_g=60.0,
    )
    assert rec.instant_coffee_g is not None
    assert rec.instant_coffee_g == pytest.approx(rec.recommended_mg / 60, abs=0.05)


# ----- 減衰カーブ -----


def test_predict_decay_curve_rises_then_decays():
    intake = datetime(2026, 5, 19, 9, 0, tzinfo=JST)
    bed = datetime(2026, 5, 19, 22, 30, tzinfo=JST)
    curve = predict_decay_curve(
        dose_mg=60, intake_time=intake, bedtime=bed, body_weight_kg=56, step_min=30
    )
    assert len(curve) > 0
    concentrations = [p["concentration_mg_per_l"] for p in curve]
    assert concentrations[0] == pytest.approx(0.0, abs=1e-6)  # t=0 は未吸収
    peak_idx = concentrations.index(max(concentrations))
    assert peak_idx >= 1  # 立ち上がり相が存在する
    # 頂値まで単調増加
    for i in range(1, peak_idx + 1):
        assert concentrations[i] >= concentrations[i - 1] - 1e-9
    # 頂値以降は単調減少
    for i in range(peak_idx + 1, len(concentrations)):
        assert concentrations[i] <= concentrations[i - 1] + 1e-9


def test_predict_decay_curve_empty_when_zero_dose():
    intake = datetime(2026, 5, 19, 9, 0, tzinfo=JST)
    bed = datetime(2026, 5, 19, 22, 30, tzinfo=JST)
    assert predict_decay_curve(
        dose_mg=0, intake_time=intake, bedtime=bed, body_weight_kg=56
    ) == []


def test_recommend_existing_residual_reduces_max():
    """既に体内にカフェインが残っている場合、上限が下がる。"""
    now = datetime(2026, 5, 19, 13, 0, tzinfo=JST)
    base = recommend_caffeine(
        now=now,
        bedtime_jst_hhmm="22:30",
        body_weight_kg=56,
    )
    # 60mg 残っている前提 (max_dose_for_bedtime 経由で減算される、recommend_caffeine は
    # existing_residual_mg を受けないので max_dose 関数の側で確認済み)
    reduced = max_dose_for_bedtime(
        hours_until_bedtime=base.hours_until_bedtime,
        body_weight_kg=56,
        existing_residual_mg=60,
    )
    assert reduced < base.max_safe_mg


def test_bedtime_crosses_midnight():
    """就寝が翌日 00:30 のケース (深夜帯)。"""
    now = datetime(2026, 5, 19, 18, 0, tzinfo=JST)
    rec = recommend_caffeine(
        now=now,
        bedtime_jst_hhmm="00:30",  # 翌日
        body_weight_kg=56,
        cutoff_hours_before_bed=6.0,
    )
    # 18:00 → 翌 00:30 = 6.5h あり
    assert rec.hours_until_bedtime == pytest.approx(6.5, abs=0.05)

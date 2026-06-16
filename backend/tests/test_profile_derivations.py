from __future__ import annotations

import pytest

from app.scoring.profile import (
    derive_caffeine_half_life_h,
    derive_max_hr,
    derive_target_mg_per_kg,
)

# ----- カフェイン半減期の導出 -----


def test_half_life_no_factors_is_base():
    h = derive_caffeine_half_life_h(
        5.0, smoker=False, oral_contraceptives=False, pregnant=False, override_h=None
    )
    assert h == pytest.approx(5.0)


def test_half_life_smoker_shortens():
    h = derive_caffeine_half_life_h(
        5.0, smoker=True, oral_contraceptives=False, pregnant=False, override_h=None
    )
    assert h == pytest.approx(3.0, abs=0.01)  # 5 * 0.6


def test_half_life_oc_lengthens():
    h = derive_caffeine_half_life_h(
        5.0, smoker=False, oral_contraceptives=True, pregnant=False, override_h=None
    )
    assert h == pytest.approx(9.0, abs=0.01)  # 5 * 1.8


def test_half_life_clamped_to_max():
    # 妊娠 + 避妊薬 = 5*2.6*1.8 = 23.4h → 12h にクランプ
    h = derive_caffeine_half_life_h(
        5.0, smoker=False, oral_contraceptives=True, pregnant=True, override_h=None
    )
    assert h == 12.0


def test_half_life_override_wins_and_clamps():
    assert derive_caffeine_half_life_h(
        5.0, smoker=True, oral_contraceptives=False, pregnant=False, override_h=7.5
    ) == pytest.approx(7.5)
    # 範囲外の override はクランプ
    assert derive_caffeine_half_life_h(
        5.0, smoker=False, oral_contraceptives=False, pregnant=False, override_h=99
    ) == 12.0


# ----- 目標 mg/kg (感受性) -----


def test_target_mg_per_kg_sensitivity():
    assert derive_target_mg_per_kg("high", 1.0) == 0.5
    assert derive_target_mg_per_kg("normal", 1.0) == 1.0
    assert derive_target_mg_per_kg("low", 1.0) == 1.5
    # 未知値は default
    assert derive_target_mg_per_kg("???", 1.0) == 1.0


# ----- 最大心拍 -----


def test_max_hr_formula_tanaka():
    # 208 - 0.7*30 = 187
    assert derive_max_hr(None, 30) == 187


def test_max_hr_override_wins():
    assert derive_max_hr(195, 30) == 195

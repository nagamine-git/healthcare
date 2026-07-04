from __future__ import annotations

import pytest

from app.scoring.population_norms import (
    bmi,
    build_distribution,
    ffmi,
    norm_for,
    percentile,
)


def test_percentile_at_mean_is_50():
    mean, _sd = norm_for("bmi", 35, "male")
    assert mean == pytest.approx(23.9)
    p = percentile("bmi", mean, 35, "male")
    assert p == pytest.approx(50.0, abs=0.5)


def test_percentile_monotonic():
    lo = percentile("bmi", 22.0, 35, "male")
    hi = percentile("bmi", 27.0, 35, "male")
    assert lo is not None and hi is not None
    assert hi > lo


def test_percentile_clamped_0_100():
    assert 0.0 <= percentile("bmi", 5.0, 35, "male") <= 100.0
    assert 0.0 <= percentile("bmi", 60.0, 35, "male") <= 100.0


def test_percentile_missing_profile_returns_none():
    assert percentile("bmi", 23.0, None, "male") is None
    assert percentile("bmi", 23.0, 35, None) is None
    assert percentile("bmi", None, 35, "male") is None


def test_bmi_calc():
    assert bmi(72.0, 175.0) == pytest.approx(72.0 / (1.75 ** 2), abs=1e-6)
    assert bmi(72.0, 0) is None
    assert bmi(None, 175.0) is None


def test_ffmi_calc():
    # 除脂肪量 = 72 * (1-0.20) = 57.6kg → /1.75^2
    expected = (72.0 * 0.8) / (1.75 ** 2)
    assert ffmi(72.0, 20.0, 175.0) == pytest.approx(expected, abs=1e-6)
    assert ffmi(72.0, None, 175.0) is None  # 体脂肪率欠損
    assert ffmi(72.0, 20.0, 0) is None


def test_build_distribution_evaluable():
    d = build_distribution(
        weight_kg=72.0, body_fat_pct=20.0, age=35, sex="male", height_cm=175.0,
        target_weight_kg=70.0, target_body_fat_pct=15.0, body_fat_tolerance_pct=2.0,
        vo2max=48.0,
    )
    assert d["evaluable"] is True
    by_key = {m["key"]: m for m in d["metrics"]}
    assert {"bmi", "body_fat", "ffmi", "vo2max"} == set(by_key)
    assert by_key["bmi"]["value"] == pytest.approx(23.5, abs=0.1)
    assert by_key["bmi"]["percentile"] is not None
    # 3指標とも範囲 (帯)。体脂肪率の目標範囲 = 15 ± 2
    assert by_key["body_fat"]["target_low"] == pytest.approx(13.0, abs=0.1)
    assert by_key["body_fat"]["target_high"] == pytest.approx(17.0, abs=0.1)
    # BMI 範囲 (除脂肪量一定で体脂肪率±2 → 体重スイング)。FFM=70*0.85=59.5
    ffm = 70.0 * 0.85
    bmi_lo = (ffm / (1 - 13 / 100)) / (1.75 ** 2)
    bmi_hi = (ffm / (1 - 17 / 100)) / (1.75 ** 2)
    assert by_key["bmi"]["target_low"] == pytest.approx(bmi_lo, abs=0.1)
    assert by_key["bmi"]["target_high"] == pytest.approx(bmi_hi, abs=0.1)
    assert by_key["bmi"]["target_low"] < by_key["bmi"]["target_high"]
    # FFMI 範囲 (目標体重固定で体脂肪率±2)。体脂肪13%→FFMI高、17%→FFMI低
    ffmi_hi = (70.0 * (1 - 13 / 100)) / (1.75 ** 2)
    ffmi_lo = (70.0 * (1 - 17 / 100)) / (1.75 ** 2)
    assert by_key["ffmi"]["target_low"] == pytest.approx(ffmi_lo, abs=0.1)
    assert by_key["ffmi"]["target_high"] == pytest.approx(ffmi_hi, abs=0.1)
    assert by_key["ffmi"]["target_low"] < by_key["ffmi"]["target_high"]
    assert by_key["ffmi"]["value"] == pytest.approx(18.8, abs=0.1)
    # VO2max=48 は 30-49男性 平均41 を上回る → percentile > 50
    assert by_key["vo2max"]["value"] == pytest.approx(48.0, abs=0.1)
    assert by_key["vo2max"]["percentile"] > 50


def test_build_distribution_missing_body_fat():
    d = build_distribution(
        weight_kg=72.0, body_fat_pct=None, age=35, sex="male", height_cm=175.0,
    )
    by_key = {m["key"]: m for m in d["metrics"]}
    assert by_key["bmi"]["value"] is not None  # BMIは出る
    assert by_key["body_fat"]["value"] is None  # 体脂肪率欠損
    assert by_key["ffmi"]["value"] is None  # FFMIも算出不能


def test_build_distribution_not_evaluable_without_profile():
    d = build_distribution(
        weight_kg=72.0, body_fat_pct=20.0, age=None, sex=None, height_cm=None,
    )
    assert d["evaluable"] is False
    for m in d["metrics"]:
        assert m["percentile"] is None  # percentileは出さない

def test_vo2max_target_band_from_body_goal():
    """VO2max の目標帯 = [目標体重でも絶対能力を守る値, 同年代上位10%]。"""
    from app.scoring.population_norms import build_distribution

    out = build_distribution(
        weight_kg=55.6, body_fat_pct=15.0, age=31, sex="male", height_cm=186.0,
        target_weight_kg=60.0, target_body_fat_pct=12.0, body_fat_tolerance_pct=1.5,
        vo2max=48.9,
    )
    vo2 = next(m for m in out["metrics"] if m["key"] == "vo2max")
    # 下限: 48.9 × 55.6/60 = 45.3 / 上限: 41 + 1.28×8 = 51.2
    assert vo2["target_low"] == 45.3
    assert vo2["target_high"] == 51.2


def test_vo2max_target_band_absent_without_inputs():
    from app.scoring.population_norms import build_distribution

    out = build_distribution(
        weight_kg=55.6, body_fat_pct=15.0, age=31, sex="male", height_cm=186.0,
        target_weight_kg=60.0, target_body_fat_pct=12.0, body_fat_tolerance_pct=1.5,
        vo2max=None,  # 値が無ければ帯も出さない
    )
    vo2 = next(m for m in out["metrics"] if m["key"] == "vo2max")
    assert vo2["target_low"] is None and vo2["target_high"] is None


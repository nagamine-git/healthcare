from __future__ import annotations


def test_compute_target_known_values():
    from app.scoring.body_composition import compute_target

    # 165cm, 体脂肪15%, 正規化FFMI 18 (細身)
    # ffmi_raw = 18 - 6.1*(1.8-1.65) = 18 - 0.915 = 17.085
    # lbm = 17.085 * 1.65^2 = 17.085 * 2.7225 = 46.51
    # weight = 46.51 / 0.85 = 54.7
    out = compute_target(165.0, 15.0, 18.0)
    assert abs(out["lbm_kg"] - 46.51) < 0.2
    assert abs(out["weight_kg"] - 54.7) < 0.3
    assert abs(out["bmi"] - 20.1) < 0.2


def test_compute_target_muscular_is_heavier():
    from app.scoring.body_composition import compute_target

    slim = compute_target(165.0, 13.0, 18.0)
    muscular = compute_target(165.0, 13.0, 22.0)
    # 同じ体脂肪率でも筋肉が多い (FFMI高) ほど重い
    assert muscular["weight_kg"] > slim["weight_kg"] + 5


def test_assess_flags_low_bmi():
    from app.scoring.body_composition import assess

    a = assess(weight_kg=48.0, bmi=17.6, body_fat_pct=12.0, sex="male")
    assert a["level"] == "warning"
    assert any("低体重" in w for w in a["warnings"])


def test_assess_blocks_severe_underweight():
    from app.scoring.body_composition import assess

    a = assess(weight_kg=42.0, bmi=15.4, body_fat_pct=10.0, sex="male")
    assert a["level"] == "blocked"


def test_assess_flags_low_body_fat_by_sex():
    from app.scoring.body_composition import assess

    male = assess(weight_kg=55.0, bmi=20.2, body_fat_pct=8.0, sex="male")
    female = assess(weight_kg=55.0, bmi=20.2, body_fat_pct=14.0, sex="female")
    assert any("体脂肪" in w for w in male["warnings"])
    assert any("体脂肪" in w for w in female["warnings"])  # 女性は16%未満で警告


def test_assess_healthy_is_ok():
    from app.scoring.body_composition import assess

    a = assess(weight_kg=55.0, bmi=20.2, body_fat_pct=15.0, sex="male")
    assert a["level"] == "ok"
    assert a["warnings"] == []

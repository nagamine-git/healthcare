from __future__ import annotations


def test_whtr_known_value():
    from app.scoring.body_measurement import whtr

    # ウエスト 85cm, 身長 170cm -> 0.5 ちょうど
    assert whtr(85.0, 170.0) == 0.5


def test_whtr_missing_is_none():
    from app.scoring.body_measurement import whtr

    assert whtr(None, 170.0) is None
    assert whtr(85.0, None) is None
    assert whtr(85.0, 0) is None


def test_whtr_status_boundaries():
    from app.scoring.body_measurement import whtr_status

    assert whtr_status(0.49) == "good"
    assert whtr_status(0.5) == "caution"  # 0.5 未満のみ good (半分"未満")
    assert whtr_status(0.59) == "caution"
    assert whtr_status(0.6) == "high"
    assert whtr_status(0.65) == "high"
    assert whtr_status(None) is None


def test_navy_body_fat_pct_known_value():
    from app.scoring.body_measurement import navy_body_fat_pct

    # waist=85cm, neck=38cm, height=170cm (男性)。
    # 原式 (Hodgdon & Beckett 1984) はインチ較正のため cm->インチ変換して代入する。
    # waist_in=33.4646, neck_in=14.9606, diff_in=18.5039, height_in=66.9291
    # 86.010*log10(18.5039) - 70.041*log10(66.9291) + 36.76 ≈ 17.9
    pct = navy_body_fat_pct(85.0, 38.0, 170.0, "male")
    assert pct is not None
    assert abs(pct - 17.9) < 0.2


def test_navy_body_fat_pct_female_returns_none():
    from app.scoring.body_measurement import navy_body_fat_pct

    assert navy_body_fat_pct(75.0, 33.0, 160.0, "female") is None


def test_navy_body_fat_pct_missing_is_none():
    from app.scoring.body_measurement import navy_body_fat_pct

    assert navy_body_fat_pct(None, 38.0, 170.0, "male") is None
    assert navy_body_fat_pct(85.0, None, 170.0, "male") is None
    assert navy_body_fat_pct(85.0, 38.0, None, "male") is None


def test_navy_body_fat_pct_invalid_measurement_is_none():
    from app.scoring.body_measurement import navy_body_fat_pct

    # 首がウエスト以上 = 測定ミス/異常値
    assert navy_body_fat_pct(30.0, 38.0, 170.0, "male") is None


def test_bia_navy_discrepancy_close_vs_large():
    from app.scoring.body_measurement import bia_navy_discrepancy

    close = bia_navy_discrepancy(20.0, 17.9)
    assert close["status"] == "close"
    assert close["diff_pt"] == 2.1

    large = bia_navy_discrepancy(26.0, 17.9)
    assert large["status"] == "large"


def test_bia_navy_discrepancy_missing_is_none():
    from app.scoring.body_measurement import bia_navy_discrepancy

    assert bia_navy_discrepancy(None, 17.9) is None
    assert bia_navy_discrepancy(20.0, None) is None


# ----- 表示用の丸め -----


def test_discrepancy_values_are_rounded():
    """BIA/海軍式の値を生の float のまま持ち回らない。

    回帰テスト: `17.68893693789233%` のような桁がそのまま API から返り、
    UI で桁溢れして隣の数値と重なる表示崩れが起きた。BIA は元々 ±3-5pt の誤差が
    ある推定値なので、この桁数は**精度の錯覚**でもある。
    """
    from app.scoring.body_measurement import bia_navy_discrepancy

    d = bia_navy_discrepancy(17.68893693789233, 19.43219)
    assert d is not None
    # 0.1pt 単位に丸まっていること (小数第2位以下を持たない)
    for key in ("bia_pct", "navy_pct", "diff_pt"):
        assert round(d[key], 1) == d[key], f"{key} が丸められていない: {d[key]}"
    assert d["bia_pct"] == 17.7
    assert d["navy_pct"] == 19.4

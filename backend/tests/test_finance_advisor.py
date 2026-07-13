"""資産の最善手アドバイザー (build_advisor) の純関数テスト。DB 非依存。"""

from __future__ import annotations

from app.scoring.finance_advisor import AdvisorInputs, build_advisor


def _inp(**kw) -> AdvisorInputs:
    base = dict(
        gross=0.0, debt=0.0, debt_rate_pct=None,
        avg_income=None, avg_expense=None, avg_net=None,
        unallocated=0.0, reserve=0.0, suggested_reserve=None,
        housing_cost=None, nisa_monthly=None, ideco_monthly=None,
    )
    base.update(kw)
    return AdvisorInputs(**base)


def _dkeys(res) -> set[str]:
    return {d["key"] for d in res["diagnosis"]}


def _mkinds(res) -> list[str]:
    return [m["kind"] for m in res["moves"]]  # priority 降順


def test_headline_is_gross_times_net():
    res = build_advisor(_inp(gross=1000.0, debt=400.0))
    assert res["gross"] == 1000.0
    assert res["net"] == 600.0  # gross - debt
    assert res["headline"] == 1000.0 * 600.0


def test_leverage_none_when_no_debt():
    assert build_advisor(_inp(gross=1000.0, debt=0.0))["leverage"] == "none"


def test_leverage_good_when_low_rate():
    res = build_advisor(_inp(gross=1000.0, debt=300.0, debt_rate_pct=1.0))
    assert res["leverage"] == "good"


def test_leverage_bad_when_high_rate():
    res = build_advisor(_inp(gross=1000.0, debt=300.0, debt_rate_pct=15.0))
    assert res["leverage"] == "bad"


def test_leverage_caution_when_mid_rate():
    res = build_advisor(_inp(gross=1000.0, debt=300.0, debt_rate_pct=5.0))
    assert res["leverage"] == "caution"


def test_bad_debt_is_top_priority_move():
    res = build_advisor(_inp(
        gross=1000.0, debt=300.0, debt_rate_pct=15.0,
        avg_income=40.0, avg_net=5.0, unallocated=200.0,
    ))
    assert "bad_debt" in _dkeys(res)
    # 悪い借金の返済が最優先 (確実なリターン)
    assert res["moves"][0]["kind"] == "debt"


def test_cash_drag_diagnosis_and_move():
    res = build_advisor(_inp(gross=1000.0, unallocated=250.0, avg_income=40.0, avg_net=10.0))
    assert "cash_drag" in _dkeys(res)
    assert "invest" in _mkinds(res)


def test_low_savings_rate_flagged():
    # 収入40, 純額2 → 貯蓄率5% (<15%)
    res = build_advisor(_inp(gross=100.0, avg_income=40.0, avg_net=2.0))
    assert "savings_rate" in _dkeys(res)
    assert "savings" in _mkinds(res)


def test_healthy_savings_not_flagged():
    # 貯蓄率30% は健全 → savings_rate 診断は出ない
    res = build_advisor(_inp(gross=100.0, avg_income=40.0, avg_net=12.0))
    assert "savings_rate" not in _dkeys(res)


def test_housing_burden_flagged():
    # 住居費18 / 収入40 = 45% (>30%)
    res = build_advisor(_inp(gross=100.0, avg_income=40.0, avg_net=10.0, housing_cost=18.0))
    assert "housing_burden" in _dkeys(res)


def test_reserve_gap_move_before_cash_drag():
    # 防衛資金不足 かつ 現金ドラッグ → 防衛資金確保が現金投資より先
    res = build_advisor(_inp(
        gross=1000.0, reserve=50.0, suggested_reserve=200.0, unallocated=300.0,
        avg_income=40.0, avg_net=10.0,
    ))
    kinds = _mkinds(res)
    assert "reserve" in kinds and "invest" in kinds
    assert kinds.index("reserve") < kinds.index("invest")


def test_move_priority_order_full():
    # 悪い借金 > 防衛資金 > 現金ドラッグ の順
    res = build_advisor(_inp(
        gross=1000.0, debt=200.0, debt_rate_pct=14.0,
        reserve=0.0, suggested_reserve=150.0, unallocated=300.0,
        avg_income=40.0, avg_net=3.0,
    ))
    kinds = _mkinds(res)
    assert kinds.index("debt") < kinds.index("reserve") < kinds.index("invest")


def test_graceful_when_no_data():
    res = build_advisor(_inp())
    assert res["has_data"] is False
    assert res["diagnosis"] == []
    assert res["moves"] == []


def test_start_nisa_suppressed_when_already_using():
    # 既に NISA を使っている → 「NISAを始める」を出さない(eMAXIS NISA 保有済みの誤提案対策)
    res = build_advisor(_inp(gross=1000.0, avg_income=40.0, avg_net=10.0, has_nisa=True))
    assert not any(m["kind"] == "tax" for m in res["moves"])


def test_start_nisa_shown_when_not_using():
    res = build_advisor(_inp(gross=1000.0, avg_income=40.0, avg_net=10.0, has_nisa=False))
    assert any(m["kind"] == "tax" for m in res["moves"])

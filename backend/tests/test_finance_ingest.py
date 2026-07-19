"""MoneyForward 何でもスクショ取込の統合ロジック (consolidate_finance_ocr) の純関数テスト。"""

from __future__ import annotations

from app.scoring.finance_ingest import consolidate_finance_ocr


def test_dedup_exact_same_row_across_images():
    # 同じ行が別画像に写った重複 (名前・金額とも一致、大小無視) → 1 つに集約し高確度を採用
    results = [
        {"assets": [{"name": "UFJ 普通", "value": 120, "confidence": "low"}]},
        {"assets": [{"name": "ufj 普通", "value": 120, "confidence": "high"}]},
    ]
    out = consolidate_finance_ocr(results)
    assert len(out["committed"]["assets"]) == 1  # 重複除去
    assert out["committed"]["assets"][0]["confidence"] == "high"


def test_same_name_different_value_kept_separate():
    # 同名でも金額が違えば別保有 (NISA / 特定口座 等) → 潰さず両方残す (バグ修正)
    results = [
        {"assets": [{"name": "eMAXIS Slim S&P500", "value": 500000, "confidence": "high"}]},
        {"assets": [{"name": "eMAXIS Slim S&P500", "value": 300000, "confidence": "high"}]},
    ]
    out = consolidate_finance_ocr(results)
    assert len(out["committed"]["assets"]) == 2
    assert {a["value"] for a in out["committed"]["assets"]} == {500000, 300000}


def test_only_high_confidence_is_committed():
    results = [{"assets": [
        {"name": "A", "value": 1, "confidence": "high"},
        {"name": "B", "value": 2, "confidence": "low"},
        {"name": "C", "value": 3, "confidence": "medium"},
    ]}]
    out = consolidate_finance_ocr(results)
    names = {a["name"] for a in out["committed"]["assets"]}
    assert names == {"A"}  # high のみ確定
    skipped = {s["name"] for s in out["skipped"]}
    assert skipped == {"B", "C"}  # medium/low は要確認へ


def test_debts_go_to_committed():
    results = [{"debts": [{"name": "住宅ローン", "value": 1000, "confidence": "high"}]}]
    out = consolidate_finance_ocr(results)
    assert len(out["committed"]["debts"]) == 1
    assert out["committed"]["debts"][0]["value"] == 1000


def test_income_expense_high_committed_medium_skipped():
    high = consolidate_finance_ocr([{"income_monthly": 40, "expense_monthly": 30, "flow_confidence": "high"}])
    assert high["committed"]["income_monthly"] == 40
    assert high["committed"]["expense_monthly"] == 30

    mid = consolidate_finance_ocr([{"income_monthly": 40, "expense_monthly": 30, "flow_confidence": "medium"}])
    assert mid["committed"]["income_monthly"] is None
    assert {s["type"] for s in mid["skipped"]} == {"income", "expense"}


def test_income_picks_highest_confidence_across_images():
    results = [
        {"income_monthly": 10, "flow_confidence": "low"},
        {"income_monthly": 42, "flow_confidence": "high"},
    ]
    out = consolidate_finance_ocr(results)
    assert out["committed"]["income_monthly"] == 42  # 高確度を採用


def test_empty_input():
    out = consolidate_finance_ocr([])
    assert out["committed"]["assets"] == [] and out["committed"]["debts"] == []
    assert out["committed"]["income_monthly"] is None
    assert out["skipped"] == []

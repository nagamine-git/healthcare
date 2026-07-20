"""corporate_finance: freee 試算表の解析 + 「なんで減ってる」診断。"""

from __future__ import annotations

from datetime import date

from app.db import session_scope
from app.models.health import CorporateFinanceSnapshot
from app.scoring.corporate_finance import compute_corporate_finance, parse_trial_bs, parse_trial_pl

# 実際に本番の freee 試算表 API から取得した形 (株式会社EFG technologies, 2026-07-20 時点) を単純化。
SAMPLE_TRIAL_BS = {
    "company_id": 2395998,
    "fiscal_year": 2026,
    "balances": [
        {"account_item_name": "三菱UFJ銀行", "account_category_name": "現金・預金",
         "hierarchy_level": 3, "closing_balance": 6074079},
        {"account_item_name": "GMOあおぞらネット銀行", "account_category_name": "現金・預金",
         "hierarchy_level": 3, "closing_balance": 401122},
        {"account_category_name": "資産", "total_line": True, "hierarchy_level": 1,
         "closing_balance": 6650174},
        {"account_category_name": "負債", "total_line": True, "hierarchy_level": 1,
         "closing_balance": 5502748},
        {"account_category_name": "純資産", "total_line": True, "hierarchy_level": 1,
         "closing_balance": 1147426},
        {"account_category_name": "当期純損益金額", "total_line": True, "hierarchy_level": 5,
         "parent_account_category_name": "その他利益剰余金", "closing_balance": -1694555},
    ],
}


# 実際に本番の freee 損益計算書 API から取得した形 (同社) を単純化。
SAMPLE_TRIAL_PL = {
    "fiscal_year": 2026,
    "balances": [
        {"account_category_name": "売上高", "total_line": True, "hierarchy_level": 1,
         "closing_balance": 779182},
        {"account_item_name": "役員報酬", "account_category_name": "販売管理費",
         "hierarchy_level": 3, "closing_balance": 539998},
        {"account_item_name": "法定福利費", "account_category_name": "販売管理費",
         "hierarchy_level": 3, "closing_balance": 75660},
        {"account_item_name": "通信費", "account_category_name": "販売管理費",
         "hierarchy_level": 3, "closing_balance": 487375},
        {"account_item_name": "消耗品費", "account_category_name": "販売管理費",
         "hierarchy_level": 3, "closing_balance": 217942},
        {"account_item_name": "地代家賃", "account_category_name": "販売管理費",
         "hierarchy_level": 3, "closing_balance": 150000},
        {"account_item_name": "租税公課", "account_category_name": "販売管理費",
         "hierarchy_level": 3, "closing_balance": 680600},
        {"account_item_name": "減価償却費", "account_category_name": "販売管理費",
         "hierarchy_level": 3, "closing_balance": 128850},
        {"account_category_name": "販売管理費", "total_line": True, "hierarchy_level": 2,
         "closing_balance": 2348722},
        {"account_category_name": "営業損益金額", "total_line": True, "hierarchy_level": 1,
         "closing_balance": -1629166},
    ],
}


def test_parse_trial_pl_extracts_revenue_and_top_expenses():
    parsed = parse_trial_pl(SAMPLE_TRIAL_PL)
    assert parsed["revenue_jpy"] == 779182
    assert parsed["operating_income_jpy"] == -1629166
    # 降順ソート、上位5件まで
    assert parsed["top_expense_categories"][0] == {"name": "租税公課", "amount": 680600}
    assert parsed["top_expense_categories"][1] == {"name": "役員報酬", "amount": 539998}
    assert len(parsed["top_expense_categories"]) == 5


def test_parse_trial_pl_missing_fields_are_none_or_empty():
    assert parse_trial_pl({"balances": []}) == {
        "revenue_jpy": None, "operating_income_jpy": None, "top_expense_categories": [],
    }


def test_parse_trial_bs_extracts_headline_figures():
    parsed = parse_trial_bs(SAMPLE_TRIAL_BS)
    assert parsed["total_assets_jpy"] == 6650174
    assert parsed["total_liabilities_jpy"] == 5502748
    assert parsed["net_assets_jpy"] == 1147426
    assert parsed["ytd_net_income_jpy"] == -1694555
    assert parsed["cash_jpy"] == 6074079 + 401122
    assert parsed["fiscal_year"] == 2026


def test_parse_trial_bs_missing_fields_are_none():
    assert parse_trial_bs({"balances": []}) == {
        "total_assets_jpy": None, "total_liabilities_jpy": None, "net_assets_jpy": None,
        "ytd_net_income_jpy": None, "cash_jpy": 0.0, "fiscal_year": None,
    }


def test_compute_corporate_finance_flags_deficit(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), company_name="株式会社EFG technologies",
            total_assets_jpy=6650174, total_liabilities_jpy=5502748, net_assets_jpy=1147426,
            ytd_net_income_jpy=-1694555, cash_jpy=6475201, fiscal_year=2026,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result is not None
    assert result["net_assets_jpy"] == 1147426
    assert result["ytd_net_income_jpy"] == -1694555
    assert any(d["key"] == "deficit" for d in result["diagnosis"])


def test_compute_corporate_finance_no_snapshot_returns_none(db_engine):
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result is None


def test_compute_corporate_finance_trend_vs_previous_snapshot(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 10), net_assets_jpy=1300000, ytd_net_income_jpy=-1500000,
        ))
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), net_assets_jpy=1147426, ytd_net_income_jpy=-1694555,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["net_assets_change_jpy"] == 1147426 - 1300000  # 純資産が減少


def test_compute_corporate_finance_headline_and_leverage_bad(db_engine):
    # 実データ相当: 負債5,502,748 / 純資産1,147,426 → 比率4.8倍 (>3) → bad
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555, cash_jpy=6475201,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["headline"] == 6650174 * 1147426
    assert result["leverage"] == "bad"


def test_compute_corporate_finance_leverage_good_when_low_debt(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=3000000, total_liabilities_jpy=200000,
            net_assets_jpy=2800000, ytd_net_income_jpy=100000,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["leverage"] == "good"


def test_compute_corporate_finance_leverage_none_when_no_debt(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=1000000, total_liabilities_jpy=0,
            net_assets_jpy=1000000, ytd_net_income_jpy=50000,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["leverage"] == "none"


def test_compute_corporate_finance_insolvent_when_net_assets_negative(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=1000000, total_liabilities_jpy=1500000,
            net_assets_jpy=-500000, ytd_net_income_jpy=-800000,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["leverage"] == "bad"
    assert any(d["key"] == "insolvent" for d in result["diagnosis"])
    assert result["moves"][0]["kind"] == "capital"  # 債務超過は最優先


def test_compute_corporate_finance_moves_prioritized_deficit_then_savings(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    kinds = [m["kind"] for m in result["moves"]]
    assert "leverage" in kinds
    assert "deficit" in kinds
    # 優先順位降順で並んでいる
    assert result["moves"] == sorted(result["moves"], key=lambda m: -m["priority"])


def test_compute_corporate_finance_declining_trend_adds_move(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 10), net_assets_jpy=1300000, total_assets_jpy=6800000,
            total_liabilities_jpy=5500000, ytd_net_income_jpy=-1500000,
        ))
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), net_assets_jpy=1147426, total_assets_jpy=6650174,
            total_liabilities_jpy=5502748, ytd_net_income_jpy=-1694555,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert any(m["kind"] == "trend" for m in result["moves"])


def test_compute_corporate_finance_healthy_company_has_no_moves(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=3000000, total_liabilities_jpy=200000,
            net_assets_jpy=2800000, ytd_net_income_jpy=100000,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["diagnosis"] == []
    assert result["moves"] == []


def test_compute_corporate_finance_flags_expense_concentration(db_engine):
    # 実データ相当: 租税公課 680,600 / 売上 779,182 = 87% > 30%しきい値
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555, revenue_jpy=779182,
            top_expense_categories=[
                {"name": "租税公課", "amount": 680600}, {"name": "役員報酬", "amount": 539998},
            ],
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    d = next(x for x in result["diagnosis"] if x["key"] == "expense_concentration")
    assert "租税公課" in d["text"] and "87%" in d["text"]
    m = next(x for x in result["moves"] if x["kind"] == "expense_concentration")
    assert "租税公課" in m["text"]
    assert result["revenue_jpy"] == 779182
    assert result["top_expense_categories"][0]["name"] == "租税公課"


def test_compute_corporate_finance_no_expense_concentration_when_below_threshold(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=3000000, total_liabilities_jpy=200000,
            net_assets_jpy=2800000, ytd_net_income_jpy=100000, revenue_jpy=1000000,
            top_expense_categories=[{"name": "地代家賃", "amount": 100000}],  # 10%
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert all(x["key"] != "expense_concentration" for x in result["diagnosis"])

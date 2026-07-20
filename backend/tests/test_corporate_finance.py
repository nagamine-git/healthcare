"""corporate_finance: freee 試算表の解析 + 「なんで減ってる」診断。"""

from __future__ import annotations

from datetime import date

from app.db import session_scope
from app.models.health import CorporateFinanceSnapshot
from app.scoring.corporate_finance import compute_corporate_finance, parse_trial_bs

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

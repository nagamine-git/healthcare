"""freee_sync: 試算表 API → CorporateFinanceSnapshot への同期 (外部呼び出しはモック)。"""

from __future__ import annotations

from unittest.mock import patch

from app.db import session_scope
from app.ingest.freee_sync import sync_corporate_finance
from app.models.health import CorporateFinanceSnapshot
from app.scoring.timewindow import app_today

# 本番の freee 試算表 API から取得した形 (株式会社EFG technologies) を単純化。
SAMPLE_TRIAL_BS = {
    "fiscal_year": 2026,
    "balances": [
        {"account_category_name": "資産", "total_line": True, "hierarchy_level": 1,
         "closing_balance": 6650174},
        {"account_category_name": "負債", "total_line": True, "hierarchy_level": 1,
         "closing_balance": 5502748},
        {"account_category_name": "純資産", "total_line": True, "hierarchy_level": 1,
         "closing_balance": 1147426},
        {"account_category_name": "当期純損益金額", "total_line": True, "hierarchy_level": 5,
         "closing_balance": -1694555},
    ],
}


def test_sync_returns_not_connected_when_no_token(db_engine):
    with patch("app.integrations.freee_client.has_token", return_value=False):
        result = sync_corporate_finance()
    assert result["status"] == "not_connected"


def test_sync_persists_snapshot_for_today(db_engine):
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "株式会社EFG technologies"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=SAMPLE_TRIAL_BS),
        patch("app.integrations.freee_client.fetch_trial_pl", return_value=None),
    ):
        result = sync_corporate_finance()
    assert result["status"] == "ok"
    with session_scope() as session:
        row = session.get(CorporateFinanceSnapshot, app_today())
        assert row is not None
        assert row.company_name == "株式会社EFG technologies"
        assert row.net_assets_jpy == 1147426
        assert row.ytd_net_income_jpy == -1694555


def test_sync_persists_trial_pl_expense_breakdown(db_engine):
    trial_pl = {
        "balances": [
            {"account_category_name": "売上高", "total_line": True, "hierarchy_level": 1,
             "closing_balance": 779182},
            {"account_item_name": "租税公課", "account_category_name": "販売管理費",
             "hierarchy_level": 3, "closing_balance": 680600},
            {"account_category_name": "営業損益金額", "total_line": True, "hierarchy_level": 1,
             "closing_balance": -1629166},
        ],
    }
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "株式会社EFG technologies"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=SAMPLE_TRIAL_BS),
        patch("app.integrations.freee_client.fetch_trial_pl", return_value=trial_pl),
    ):
        result = sync_corporate_finance()
    assert result["status"] == "ok"
    with session_scope() as session:
        row = session.get(CorporateFinanceSnapshot, app_today())
        assert row.revenue_jpy == 779182
        assert row.operating_income_jpy == -1629166
        assert row.top_expense_categories == [{"name": "租税公課", "amount": 680600}]


def test_sync_ok_even_when_trial_pl_fetch_fails(db_engine):
    # trial_pl はベストエフォート。取得失敗しても trial_bs ベースの同期は成立する。
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "株式会社EFG technologies"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=SAMPLE_TRIAL_BS),
        patch("app.integrations.freee_client.fetch_trial_pl", return_value=None),
    ):
        result = sync_corporate_finance()
    assert result["status"] == "ok"


def test_sync_persists_fiscal_start_date_and_actionable_expense(db_engine):
    from datetime import date

    trial_pl = {
        "balances": [
            {"account_item_name": "租税公課", "account_category_name": "販売管理費",
             "hierarchy_level": 3, "closing_balance": 680600},
            {"account_item_name": "通信費", "account_category_name": "販売管理費",
             "hierarchy_level": 3, "closing_balance": 487375},
        ],
    }
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "株式会社EFG technologies"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=SAMPLE_TRIAL_BS),
        patch("app.integrations.freee_client.fetch_trial_pl", return_value=trial_pl),
        patch("app.integrations.freee_client.fetch_fiscal_start_date",
              return_value=date(2026, 5, 1)),
    ):
        result = sync_corporate_finance()
    assert result["status"] == "ok"
    with session_scope() as session:
        row = session.get(CorporateFinanceSnapshot, app_today())
        assert row.fiscal_start_date == date(2026, 5, 1)
        assert row.actionable_expense_ytd_jpy == 487375  # 租税公課は裁量経費から除外


def test_sync_upserts_same_day_snapshot(db_engine):
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "株式会社EFG technologies"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=SAMPLE_TRIAL_BS),
        patch("app.integrations.freee_client.fetch_trial_pl", return_value=None),
    ):
        sync_corporate_finance()
        sync_corporate_finance()
    with session_scope() as session:
        rows = session.query(CorporateFinanceSnapshot).all()
    assert len(rows) == 1  # 同日は上書き、増えない


def test_fetch_fiscal_start_date_picks_period_containing_date():
    from datetime import date

    from app.integrations import freee_client

    company = {"company": {"fiscal_years": [
        {"start_date": "2025-05-01", "end_date": "2026-04-30"},
        {"start_date": "2026-05-01", "end_date": "2027-04-30"},
    ]}}
    with patch("app.integrations.freee_client._api_get", return_value=company):
        assert freee_client.fetch_fiscal_start_date(1, date(2026, 7, 21)) == date(2026, 5, 1)
        assert freee_client.fetch_fiscal_start_date(1, date(2026, 4, 30)) == date(2025, 5, 1)


def test_fetch_fiscal_start_date_none_when_api_fails():
    from app.integrations import freee_client

    with patch("app.integrations.freee_client._api_get", return_value=None):
        assert freee_client.fetch_fiscal_start_date(1, app_today()) is None


def test_sync_error_when_trial_bs_fetch_fails(db_engine):
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "x"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=None),
    ):
        result = sync_corporate_finance()
    assert result["status"] == "error"

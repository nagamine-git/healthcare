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
    ):
        result = sync_corporate_finance()
    assert result["status"] == "ok"
    with session_scope() as session:
        row = session.get(CorporateFinanceSnapshot, app_today())
        assert row is not None
        assert row.company_name == "株式会社EFG technologies"
        assert row.net_assets_jpy == 1147426
        assert row.ytd_net_income_jpy == -1694555


def test_sync_upserts_same_day_snapshot(db_engine):
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "株式会社EFG technologies"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=SAMPLE_TRIAL_BS),
    ):
        sync_corporate_finance()
        sync_corporate_finance()
    with session_scope() as session:
        rows = session.query(CorporateFinanceSnapshot).all()
    assert len(rows) == 1  # 同日は上書き、増えない


def test_sync_error_when_trial_bs_fetch_fails(db_engine):
    with (
        patch("app.integrations.freee_client.has_token", return_value=True),
        patch("app.integrations.freee_client.get_company",
              return_value={"id": 2395998, "name": "x"}),
        patch("app.integrations.freee_client.fetch_trial_bs", return_value=None),
    ):
        result = sync_corporate_finance()
    assert result["status"] == "error"

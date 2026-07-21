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
    # 裁量経費 = 販管費のうち税・社会保険・役員報酬・減価償却を除いた合計
    assert parsed["actionable_expense_ytd_jpy"] == 487375 + 217942 + 150000


def test_parse_trial_pl_missing_fields_are_none_or_empty():
    assert parse_trial_pl({"balances": []}) == {
        "revenue_jpy": None, "operating_income_jpy": None, "top_expense_categories": [],
        "actionable_expense_ytd_jpy": None, "cogs_jpy": None,
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


def test_compute_corporate_finance_wealth_index_score_and_goal(db_engine):
    # gross=net=2,000,000 → wealth_index=2,000,000。既定target=5,000,000 → score=40, goal=50
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=2000000, total_liabilities_jpy=0,
            net_assets_jpy=2000000, ytd_net_income_jpy=50000,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["wealth_index"] == 2000000.0
    assert result["score"] == 40.0
    assert result["goal"] == 50.0


def test_compute_corporate_finance_wealth_index_none_when_insolvent(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=1000000, total_liabilities_jpy=1500000,
            net_assets_jpy=-500000, ytd_net_income_jpy=-800000,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["wealth_index"] is None
    assert result["score"] is None
    assert result["goal"] is None


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


def test_compute_corporate_finance_deficit_move_targets_actionable_expense(db_engine):
    # 実データ相当: 1位の租税公課(税)・2位の役員報酬(定期同額給与で年内変更不可)は
    # 「削れる」経費ではない。3位の通信費が実質最大の削減余地 → そこを名指しする。
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555, revenue_jpy=779182,
            top_expense_categories=[
                {"name": "租税公課", "amount": 680600},
                {"name": "役員報酬", "amount": 539998},
                {"name": "通信費", "amount": 487375},
                {"name": "消耗品費", "amount": 217942},
            ],
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    m = next(x for x in result["moves"] if x["kind"] == "deficit")
    assert "通信費" in m["text"]
    assert "租税公課" not in m["text"] and "役員報酬" not in m["text"]
    assert "487,375" in m["text"] or "487375" in m["text"]


def test_compute_corporate_finance_deficit_move_generic_when_no_actionable_expense(db_engine):
    # 上位が全て非アクションカテゴリなら、従来の汎用文言にフォールバックする。
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
    m = next(x for x in result["moves"] if x["kind"] == "deficit")
    assert "固定費(人件費・外注費等)を見直す" in m["text"]


def test_compute_corporate_finance_impulse_hold_from_actionable_expense_pace(db_engine):
    # 裁量経費 855,317円 / 期首(5/1)から 7/20 までの 81 日 = 1日あたり 10,560円 → 閾値
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555,
            actionable_expense_ytd_jpy=855317, fiscal_start_date=date(2026, 5, 1),
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["impulse_hold_jpy"] == round(855317 / 81)
    assert "81日" in result["impulse_hold_basis"]


def test_compute_corporate_finance_impulse_hold_falls_back_to_default(db_engine):
    # 費目内訳/期首日が未取込でも閾値は常時返す (既定値 + それと分かる根拠ラベル)
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["impulse_hold_jpy"] == 10000
    assert "既定値" in result["impulse_hold_basis"]


def test_compute_corporate_finance_leverage_move_includes_debt_amount(db_engine):
    # ウィジェットは moves[0].text をそのまま出すので、抽象的な文言だけでなく実額が要る。
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=100000,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    m = next(x for x in result["moves"] if x["kind"] == "leverage")
    assert f"{5502748:,}円" in m["text"]
    assert "4.8倍" in m["text"]


def test_compute_corporate_finance_capital_move_includes_net_assets_amount(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=1000000, total_liabilities_jpy=1500000,
            net_assets_jpy=-500000, ytd_net_income_jpy=-800000,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    m = next(x for x in result["moves"] if x["kind"] == "capital")
    assert f"{-500000:,}円" in m["text"]


def test_compute_corporate_finance_deficit_generic_move_includes_net_income_amount(db_engine):
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
    m = next(x for x in result["moves"] if x["kind"] == "deficit")
    assert f"{1694555:,}円" in m["text"]


def test_compute_corporate_finance_trend_move_includes_change_amount(db_engine):
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
    m = next(x for x in result["moves"] if x["kind"] == "trend")
    assert f"{1147426 - 1300000:,}円" in m["text"]


def test_compute_corporate_finance_health_score_from_three_metrics(db_engine):
    # 期首 5/1 → 7/20 は 81日 ≈ 2.66ヶ月。費用 = 売上779,182 − 営業損益(−1,629,166) = 2,408,348
    # → 月バーン ≈ 904,262。現金 6,475,201 → ランウェイ ≈ 7.2ヶ月。
    # 自己資本比率 = 1,147,426 / 6,650,174 = 17.3%
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555, cash_jpy=6475201,
            revenue_jpy=779182, operating_income_jpy=-1629166,
            fiscal_start_date=date(2026, 5, 1),
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["runway_months"] == 7.2
    assert result["equity_ratio_pct"] == 17.3
    # 3 指標すべて算出できている → 総合点は 3 つの平均
    subs = result["subscores"]
    assert all(subs[k] is not None for k in ("scale", "runway", "equity"))
    assert result["health_score"] == round(sum(subs.values()) / 3, 1)
    assert result["health_goal"] == min(100.0, result["health_score"] + 10.0)


def test_compute_corporate_finance_health_ignores_missing_metrics(db_engine):
    # 期首日も PL も無い → ランウェイ算出不可。取れた指標だけで平均する
    # (0 点扱いにすると「未取込」が「不健全」に化けるため)。
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555,
        ))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["runway_months"] is None
    assert result["subscores"]["runway"] is None
    assert result["subscores"]["equity"] is not None
    got = [v for v in result["subscores"].values() if v is not None]
    assert result["health_score"] == round(sum(got) / len(got), 1)


def test_compute_corporate_finance_health_none_when_nothing_computable(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(date=date(2026, 7, 20)))
    with session_scope() as session:
        result = compute_corporate_finance(session)
    assert result["health_score"] is None
    assert result["health_goal"] is None


def test_parse_trial_pl_extracts_cogs_for_gross_margin():
    pl = {"balances": [
        {"account_category_name": "売上高", "total_line": True, "hierarchy_level": 1,
         "closing_balance": 779182},
        {"account_category_name": "売上原価", "total_line": True, "hierarchy_level": 2,
         "closing_balance": 59626},
    ]}
    assert parse_trial_pl(pl)["cogs_jpy"] == 59626


def test_breakdown_splits_deficit_into_revenue_and_expense_paths(db_engine):
    # 赤字 1,694,555。粗利率 = (779,182 − 59,626)/779,182 = 92.3%
    # → 必要増収 = 1,694,555 / 0.923 ≈ 1,835,700
    # 裁量経費 855,317 → 必要削減率 = 198% (支出だけでは埋まらない)
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=6650174, total_liabilities_jpy=5502748,
            net_assets_jpy=1147426, ytd_net_income_jpy=-1694555,
            revenue_jpy=779182, cogs_jpy=59626, actionable_expense_ytd_jpy=855317,
            top_expense_categories=[
                {"name": "租税公課", "amount": 680600},
                {"name": "通信費", "amount": 487375},
                {"name": "消耗品費", "amount": 217942},
            ],
        ))
    with session_scope() as session:
        b = compute_corporate_finance(session)["breakdown"]
    assert b["deficit_jpy"] == 1694555
    assert b["revenue_path"]["gross_margin_pct"] == 92.3
    assert b["revenue_path"]["required_increase_jpy"] == round(1694555 / ((779182 - 59626) / 779182))
    # 支出だけでは埋まらないことを明示する
    assert b["expense_path"]["required_cut_pct"] > 100
    assert b["expense_path"]["enough_alone"] is False
    # 削れない費目 (租税公課) は経路から除外される
    names = [i["name"] for i in b["expense_path"]["items"]]
    assert "租税公課" not in names
    assert names == ["通信費", "消耗品費"]
    assert b["expense_path"]["items"][0]["covers_pct"] == round(487375 / 1694555 * 100, 1)


def test_breakdown_none_when_profitable(db_engine):
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=3000000, total_liabilities_jpy=200000,
            net_assets_jpy=2800000, ytd_net_income_jpy=100000, revenue_jpy=1000000,
        ))
    with session_scope() as session:
        assert compute_corporate_finance(session)["breakdown"] is None


def test_breakdown_expense_path_enough_alone_when_cut_is_feasible(db_engine):
    # 赤字 200,000 / 裁量経費 1,000,000 → 20% 削れば埋まる
    with session_scope() as session:
        session.add(CorporateFinanceSnapshot(
            date=date(2026, 7, 20), total_assets_jpy=3000000, total_liabilities_jpy=200000,
            net_assets_jpy=2800000, ytd_net_income_jpy=-200000,
            revenue_jpy=1000000, cogs_jpy=0, actionable_expense_ytd_jpy=1000000,
        ))
    with session_scope() as session:
        b = compute_corporate_finance(session)["breakdown"]
    assert b["expense_path"]["required_cut_pct"] == 20.0
    assert b["expense_path"]["enough_alone"] is True

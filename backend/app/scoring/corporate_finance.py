"""法人 (freee) の財務診断。個人の資産アドバイザーと同じ「なんで増えない/減ってる」設計。

freee の試算表 (trial_bs) は科目の階層構造を平坦なリストで返す。合計行は
``total_line: true`` かつ ``hierarchy_level`` でネストの深さを表す。ここでは
一番浅い (hierarchy_level=1) 合計行から資産/負債/純資産を、"当期純損益金額" の
合計行から今期の累計損益を拾う。

個人の純資産とは意図的に合算しない (別枠の参考値として扱う) — 詳細は
CorporateFinanceSnapshot のドキュメント参照。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health import CorporateFinanceSnapshot


def parse_trial_bs(trial_bs: dict[str, Any]) -> dict[str, Any]:
    """freee trial_bs レスポンス → ヘッドライン指標。無い項目は None (現金は 0.0)。"""
    total_assets = total_liabilities = net_assets = ytd_net_income = None
    cash = 0.0
    for b in trial_bs.get("balances") or []:
        cat = b.get("account_category_name")
        if b.get("total_line") and b.get("hierarchy_level") == 1:
            if cat == "資産":
                total_assets = b.get("closing_balance")
            elif cat == "負債":
                total_liabilities = b.get("closing_balance")
            elif cat == "純資産":
                net_assets = b.get("closing_balance")
        if b.get("total_line") and cat == "当期純損益金額":
            ytd_net_income = b.get("closing_balance")
        if not b.get("total_line") and cat == "現金・預金":
            cash += float(b.get("closing_balance") or 0)
    return {
        "total_assets_jpy": total_assets,
        "total_liabilities_jpy": total_liabilities,
        "net_assets_jpy": net_assets,
        "ytd_net_income_jpy": ytd_net_income,
        "cash_jpy": cash,
        "fiscal_year": trial_bs.get("fiscal_year"),
    }


_TOP_EXPENSE_LIMIT = 5


def parse_trial_pl(trial_pl: dict[str, Any]) -> dict[str, Any]:
    """freee trial_pl レスポンス → 売上/営業損益 + 費目別内訳 (降順、上位 _TOP_EXPENSE_LIMIT 件)。

    「赤字です」で終わらせず「どの費目が主因か」まで言うための内訳。個々の費目行
    (販売管理費配下、非合計行) を金額降順で並べる。COGS 内訳(売上原価配下)は今回対象外
    (この会社では影響が小さく、対象を広げると階層追跡が複雑になるため)。
    """
    revenue = operating_income = None
    items: list[dict[str, Any]] = []
    for b in trial_pl.get("balances") or []:
        cat = b.get("account_category_name")
        if b.get("total_line") and b.get("hierarchy_level") == 1:
            if cat == "売上高":
                revenue = b.get("closing_balance")
            elif cat == "営業損益金額":
                operating_income = b.get("closing_balance")
        if not b.get("total_line") and cat == "販売管理費" and b.get("account_item_name"):
            items.append({"name": b["account_item_name"], "amount": b.get("closing_balance")})
    items.sort(key=lambda x: -(x["amount"] or 0))
    return {
        "revenue_jpy": revenue,
        "operating_income_jpy": operating_income,
        "top_expense_categories": items[:_TOP_EXPENSE_LIMIT],
    }


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v))


# 負債/純資産比率のしきい値 (個人の debt_rate_pct と違い freee は金利を返さないので、
# レバレッジの良否は自己資本比率の代理指標として debt/net_assets 比で判定する)。
_LEVERAGE_BAD_RATIO = 3.0
_LEVERAGE_CAUTION_RATIO = 1.5

# 個人の housing_burden_ratio (住居費/収入 30%) と同じ発想: 1 費目が売上のこの割合を
# 超えたら「見て良い」水準として指摘する (悪いと決めつけず、確認を促す)。
_EXPENSE_CONCENTRATION_RATIO = 0.3


def _leverage(debt: float, net_assets: float | None) -> str:
    if net_assets is not None and net_assets <= 0:
        return "bad"  # 債務超過
    if debt <= 0:
        return "none"
    if net_assets is None:
        return "caution"  # 純資産不明ではレバレッジの良否を判定できない
    ratio = debt / net_assets
    if ratio > _LEVERAGE_BAD_RATIO:
        return "bad"
    if ratio > _LEVERAGE_CAUTION_RATIO:
        return "caution"
    return "good"


def compute_corporate_finance(session: Session) -> dict[str, Any] | None:
    """最新スナップショット + 「なんで増えない/減ってる」診断 + 優先順位つき最善手。

    個人の finance_advisor.build_advisor と同じ設計 (看板指標=総資産×純資産、
    診断、moves を priority 降順で返す)。取込がまだ無ければ None。
    """
    rows = list(
        session.execute(
            select(CorporateFinanceSnapshot).order_by(CorporateFinanceSnapshot.date.desc()).limit(2)
        ).scalars()
    )
    if not rows:
        return None
    latest, prev = rows[0], (rows[1] if len(rows) > 1 else None)

    gross = latest.total_assets_jpy or 0.0
    debt = latest.total_liabilities_jpy or 0.0
    net_assets = latest.net_assets_jpy
    leverage = _leverage(debt, net_assets)
    insolvent = net_assets is not None and net_assets <= 0

    diagnosis: list[dict[str, Any]] = []
    moves: list[dict[str, Any]] = []

    if insolvent:
        diagnosis.append({
            "key": "insolvent",
            "text": f"純資産がマイナス ({_r(net_assets):,}円)。債務超過の状態",
        })
        moves.append({
            "priority": 95, "kind": "capital",
            "text": "資本増強か負債圧縮を最優先で検討する",
            "why": "債務超過は財務的に最も危険な状態。放置すると倒産リスクに直結する",
        })
    elif leverage == "bad":
        ratio = debt / net_assets if net_assets else 0.0
        diagnosis.append({
            "key": "leverage",
            "text": f"負債が純資産の{ratio:.1f}倍。借入金利が事業の利益率を超えていないか確認",
        })
        moves.append({
            "priority": 80, "kind": "leverage",
            "text": "借入の返済ペースを上げるか借り換えを検討する",
            "why": "高レバレッジは金利上昇や業績悪化時の耐性を弱める",
        })

    if latest.ytd_net_income_jpy is not None and latest.ytd_net_income_jpy < 0:
        diagnosis.append({
            "key": "deficit",
            "text": f"今期は赤字進行中 (当期純損益 {_r(latest.ytd_net_income_jpy):,}円)。"
                    "売上を増やすか経費を見直す",
        })
        moves.append({
            "priority": 75, "kind": "deficit",
            "text": "売上を増やすか固定費(人件費・外注費等)を見直す",
            "why": "当期純損益がマイナスのままだと純資産は毎期削られ続ける",
        })

    # 費目の集中: 「赤字です」で終わらせず、どの費目が主因かまで言う。
    top_expenses = latest.top_expense_categories or []
    revenue = latest.revenue_jpy
    if top_expenses and revenue and revenue > 0:
        top = top_expenses[0]
        top_amount = top.get("amount") or 0
        ratio = top_amount / revenue
        if ratio > _EXPENSE_CONCENTRATION_RATIO:
            diagnosis.append({
                "key": "expense_concentration",
                "text": f"最大の費用科目は「{top['name']}」で {_r(top_amount):,}円 "
                        f"(売上の{ratio * 100:.0f}%)。計上ミスの可能性も含め内容を確認",
            })
            moves.append({
                "priority": 65, "kind": "expense_concentration",
                "text": f"「{top['name']}」({_r(top_amount):,}円、売上の{ratio * 100:.0f}%) の内容を確認する",
                "why": "1費目で売上の3割超は、単価交渉・契約見直し・計上ミスいずれかの可能性が高い",
            })

    net_assets_change: float | None = None
    if prev is not None and latest.net_assets_jpy is not None and prev.net_assets_jpy is not None:
        net_assets_change = latest.net_assets_jpy - prev.net_assets_jpy
        if net_assets_change < 0:
            moves.append({
                "priority": 55, "kind": "trend",
                "text": "前回の同期より純資産が減っている。支出の急増が無いか確認する",
                "why": "トレンドが下向きだと構造的な問題を見逃している可能性がある",
            })

    moves.sort(key=lambda m: -m["priority"])

    return {
        "date": latest.date.isoformat(),
        "company_name": latest.company_name,
        "total_assets_jpy": _r(latest.total_assets_jpy),
        "total_liabilities_jpy": _r(latest.total_liabilities_jpy),
        "net_assets_jpy": _r(net_assets),
        "ytd_net_income_jpy": _r(latest.ytd_net_income_jpy),
        "cash_jpy": _r(latest.cash_jpy),
        "fiscal_year": latest.fiscal_year,
        "revenue_jpy": _r(latest.revenue_jpy),
        "operating_income_jpy": _r(latest.operating_income_jpy),
        "top_expense_categories": top_expenses,
        "headline": gross * net_assets if net_assets is not None else None,
        "leverage": leverage,
        "diagnosis": diagnosis,
        "moves": moves,
        "net_assets_change_jpy": _r(net_assets_change),
    }

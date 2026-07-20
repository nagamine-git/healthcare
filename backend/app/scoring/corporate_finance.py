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


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v))


def compute_corporate_finance(session: Session) -> dict[str, Any] | None:
    """最新スナップショット + 診断。取込がまだ無ければ None。"""
    rows = list(
        session.execute(
            select(CorporateFinanceSnapshot).order_by(CorporateFinanceSnapshot.date.desc()).limit(2)
        ).scalars()
    )
    if not rows:
        return None
    latest, prev = rows[0], (rows[1] if len(rows) > 1 else None)

    diagnosis: list[dict[str, Any]] = []
    if latest.ytd_net_income_jpy is not None and latest.ytd_net_income_jpy < 0:
        diagnosis.append({
            "key": "deficit",
            "text": f"今期は赤字進行中 (当期純損益 {_r(latest.ytd_net_income_jpy):,}円)。"
                    "売上を増やすか経費を見直す",
        })
    if (
        latest.total_liabilities_jpy is not None
        and latest.net_assets_jpy is not None
        and latest.net_assets_jpy > 0
        and latest.total_liabilities_jpy > latest.net_assets_jpy * 3
    ):
        diagnosis.append({
            "key": "leverage",
            "text": f"負債が純資産の{latest.total_liabilities_jpy / latest.net_assets_jpy:.1f}倍。"
                    "借入金利が事業の利益率を超えていないか確認",
        })

    result: dict[str, Any] = {
        "date": latest.date.isoformat(),
        "company_name": latest.company_name,
        "total_assets_jpy": _r(latest.total_assets_jpy),
        "total_liabilities_jpy": _r(latest.total_liabilities_jpy),
        "net_assets_jpy": _r(latest.net_assets_jpy),
        "ytd_net_income_jpy": _r(latest.ytd_net_income_jpy),
        "cash_jpy": _r(latest.cash_jpy),
        "fiscal_year": latest.fiscal_year,
        "diagnosis": diagnosis,
        "net_assets_change_jpy": None,
    }
    if prev is not None and latest.net_assets_jpy is not None and prev.net_assets_jpy is not None:
        result["net_assets_change_jpy"] = _r(latest.net_assets_jpy - prev.net_assets_jpy)
    return result

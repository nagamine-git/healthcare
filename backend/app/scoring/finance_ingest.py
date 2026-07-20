"""MoneyForward 何でもスクショ取込の統合ロジック(純関数・DB非依存)。

複数画像の OCR 結果を横断で重複除去し、確度が high のものだけ「確定(committed)」に、
medium/low は「要確認(skipped)」に振り分ける。取り込む先(資産/負債/収支)は呼び出し側が
committed を見てルーティングする。
"""

from __future__ import annotations

from typing import Any

_CONF = {"high": 3, "medium": 2, "low": 1}


def _dedup(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """(name, 金額) で重複除去 — **複数画像に同じ行が写った重なりだけ**を排除する。

    重要: name **だけ** でキー化すると、同名でも金額が違う別保有 (特定口座 / NISA / つみたて 等で
    MoneyForward が同名表示するケース) を 1 つに潰してしまう。金額もキーに含めることで、
    同名異額は両方残し (後段の merge_asset_items が「名前 (2)」の連番で別行にする)、
    同名同額 (=同じ行が別画像に重複) だけを最高確度側に集約する。
    """
    best: dict[tuple[str, int], dict[str, Any]] = {}
    order: list[tuple[str, int]] = []
    for it in items:
        name = str(it.get("name") or "").strip()
        if not name or it.get("value") is None:
            continue
        value = float(it["value"])
        key = (name.lower(), round(value))
        c = _CONF.get(it.get("confidence"), 0)
        cur = best.get(key)
        if cur is None:
            order.append(key)
        cur_c = _CONF.get(cur.get("confidence"), 0) if cur else -1
        if cur is None or c > cur_c:
            best[key] = {"name": name, "value": value, "confidence": it.get("confidence") or "low"}
    return [best[k] for k in order]


def consolidate_finance_ocr(results: list[dict[str, Any]]) -> dict[str, Any]:
    """OCR 結果(画像ごと)を統合。返り値: {committed, skipped}。"""
    all_assets: list[dict[str, Any]] = []
    all_debts: list[dict[str, Any]] = []
    for r in results:
        all_assets.extend(r.get("assets") or [])
        all_debts.extend(r.get("debts") or [])

    committed: dict[str, Any] = {
        "assets": [], "debts": [], "income_monthly": None, "expense_monthly": None,
        "budget_variable_remaining_jpy": None, "budget_days_remaining": None,
    }
    skipped: list[dict[str, Any]] = []

    for a in _dedup(all_assets):
        if a["confidence"] == "high":
            committed["assets"].append(a)
        else:
            skipped.append({"type": "asset", **a})
    for d in _dedup(all_debts):
        if d["confidence"] == "high":
            committed["debts"].append(d)
        else:
            skipped.append({"type": "debt", **d})

    # 収支: 各画像のうち最高確度で income/expense を持つものを採用
    flow = [
        r for r in results
        if r.get("income_monthly") is not None or r.get("expense_monthly") is not None
    ]
    if flow:
        best = max(flow, key=lambda r: _CONF.get(r.get("flow_confidence"), 0))
        conf = best.get("flow_confidence") or "low"
        inc, exp = best.get("income_monthly"), best.get("expense_monthly")
        if conf == "high":
            committed["income_monthly"] = inc
            committed["expense_monthly"] = exp
        else:
            if inc is not None:
                skipped.append({"type": "income", "value": inc, "confidence": conf})
            if exp is not None:
                skipped.append({"type": "expense", "value": exp, "confidence": conf})

    # 予算(変動費の残り/残り日数): 各画像のうち最高確度のものを採用
    budget = [r for r in results if r.get("budget_variable_remaining_jpy") is not None]
    if budget:
        best = max(budget, key=lambda r: _CONF.get(r.get("budget_confidence"), 0))
        conf = best.get("budget_confidence") or "low"
        remaining, days = best.get("budget_variable_remaining_jpy"), best.get("budget_days_remaining")
        if conf == "high":
            committed["budget_variable_remaining_jpy"] = remaining
            committed["budget_days_remaining"] = days
        else:
            skipped.append({
                "type": "budget", "value": remaining, "days_remaining": days, "confidence": conf,
            })

    return {"committed": committed, "skipped": skipped}

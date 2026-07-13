"""MoneyForward 何でもスクショ取込の統合ロジック(純関数・DB非依存)。

複数画像の OCR 結果を横断で重複除去し、確度が high のものだけ「確定(committed)」に、
medium/low は「要確認(skipped)」に振り分ける。取り込む先(資産/負債/収支)は呼び出し側が
committed を見てルーティングする。
"""

from __future__ import annotations

from typing import Any

_CONF = {"high": 3, "medium": 2, "low": 1}


def _dedup(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """name(大小・前後空白無視)で重複除去。最高確度を採用、同確度なら大きい値。"""
    best: dict[str, dict[str, Any]] = {}
    for it in items:
        name = str(it.get("name") or "").strip()
        if not name or it.get("value") is None:
            continue
        key = name.lower()
        c = _CONF.get(it.get("confidence"), 0)
        cur = best.get(key)
        cur_c = _CONF.get(cur.get("confidence"), 0) if cur else -1
        if cur is None or c > cur_c or (c == cur_c and float(it["value"]) > cur["value"]):
            best[key] = {"name": name, "value": float(it["value"]), "confidence": it.get("confidence") or "low"}
    return list(best.values())


def consolidate_finance_ocr(results: list[dict[str, Any]]) -> dict[str, Any]:
    """OCR 結果(画像ごと)を統合。返り値: {committed, skipped}。"""
    all_assets: list[dict[str, Any]] = []
    all_debts: list[dict[str, Any]] = []
    for r in results:
        all_assets.extend(r.get("assets") or [])
        all_debts.extend(r.get("debts") or [])

    committed: dict[str, Any] = {
        "assets": [], "debts": [], "income_monthly": None, "expense_monthly": None,
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

    return {"committed": committed, "skipped": skipped}

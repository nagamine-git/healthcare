"""資産リバランス + 購入ROIランキング。2つのスプレッドシートの判断ロジックを移植。

- リバランス: 総資産(MoneyForward 転記)から生活防衛資金を引いた余剰を、目標配分へ。
  各バケットの「あといくら投資できる(目標額−現在)」と売買シグナルを出す。
- ROI: 各候補の ROI=(月削減時間×時給 + 月収益)/ 純月コスト を、活用率で重み付け(活用率×ROI)
  してランキング。余剰資金の範囲で上位から「検討」を提示。継続/解約も判定。
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health import AssetHolding, FinanceState, RoiCandidate


def _r(v: float | None, n: int = 0) -> float | None:
    return None if v is None else round(float(v), n)


def get_state(session: Session) -> FinanceState:
    st = session.get(FinanceState, 1)
    if st is None:
        st = FinanceState(id=1)
        session.add(st)
        session.flush()
    return st


def compute_rebalance(session: Session) -> dict[str, Any]:
    holdings = list(session.execute(select(AssetHolding)).scalars())
    st = get_state(session)
    total = sum(h.value_jpy for h in holdings)
    reserve = st.reserve_jpy
    investable = max(0.0, total - reserve)

    targeted = [h for h in holdings if h.target_weight > 0]
    sum_w = sum(h.target_weight for h in targeted) or 1.0
    invested_now = sum(h.value_jpy for h in targeted)

    rows: list[dict[str, Any]] = []
    for h in holdings:
        target_value = investable * (h.target_weight / sum_w) if h.target_weight > 0 else None
        room = (target_value - h.value_jpy) if target_value is not None else None
        if room is None:
            signal = "reserve"  # 配分対象外(現金/防衛資金)
        elif room > investable * 0.02:
            signal = "buy"      # 目標まで余地 → 買い増し
        elif room < -investable * 0.02:
            signal = "sell"     # 目標超過 → 利確/控える
        else:
            signal = "hold"
        rows.append({
            "id": h.id, "name": h.name, "category": h.category,
            "value_jpy": _r(h.value_jpy), "target_weight": h.target_weight,
            "target_value": _r(target_value), "room": _r(room),
            "current_ratio": _r(h.value_jpy / total * 100, 1) if total else None,
            "target_ratio": _r(h.target_weight / sum_w * 100, 1) if h.target_weight > 0 else None,
            "signal": signal, "note": h.note,
        })
    rows.sort(key=lambda r: (r["room"] is None, -(r["room"] or 0)))
    return {
        "total": _r(total), "reserve": _r(reserve), "investable": _r(investable),
        "invested_now": _r(invested_now),
        "unallocated": _r(max(0.0, investable - invested_now)),  # 余剰のうち未配分=投資余地
        "holdings": rows,
        "wage_jpy_per_h": _r(st.wage_jpy_per_h),
    }


def _monthly_cost(c: RoiCandidate) -> float:
    if c.period == "month":
        return c.cost_jpy
    if c.period == "year":
        return c.cost_jpy / 12.0
    return c.cost_jpy / 12.0  # 買い切りは 12ヶ月で按分(シート踏襲)


def _utilization(use_days: float) -> float:
    # 月間活用日数 → 活用率(平方根カーブ。34→~1.1, 21→~0.8, 8→~0.5, 1→~0.2)。
    if use_days <= 0:
        return 0.0
    return round(min(1.1, math.sqrt(use_days / 30.0) * 1.1), 2)


def compute_roi_ranking(session: Session, investable: float, wage: float) -> dict[str, Any]:
    cands = list(session.execute(select(RoiCandidate)).scalars())
    rows: list[dict[str, Any]] = []
    for c in cands:
        mcost = _monthly_cost(c)
        net_cost = max(1.0, mcost - c.resale_jpy / 24.0)  # 資産性は24ヶ月で回収可能とみなす
        value = c.monthly_time_saved_h * wage + c.monthly_revenue_jpy
        roi = value / net_cost
        util = _utilization(c.monthly_use_days)
        score = round(util * roi, 2)
        # 継続/解約・購入判断: 活用率×ROI が 1 未満は妙味薄(衝動買い注意/解約候補)。
        if c.status == "owning":
            verdict = "continue" if score >= 1.0 else "cancel"
        else:
            verdict = "buy" if score >= 1.0 else ("watch" if score >= 0.5 else "skip")
        rows.append({
            "id": c.id, "name": c.name, "url": c.url, "status": c.status,
            "monthly_cost": _r(mcost), "roi": round(roi, 2), "utilization": util,
            "score": score, "verdict": verdict,
            "monthly_time_saved_h": c.monthly_time_saved_h,
            "monthly_revenue_jpy": _r(c.monthly_revenue_jpy), "resale_jpy": _r(c.resale_jpy),
            "period": c.period, "cost_jpy": _r(c.cost_jpy),
        })
    rows.sort(key=lambda r: -r["score"])

    # 余剰資金の範囲で上位から「今すぐ検討」に入るものをマーク(買い切り価格の累積)。
    budget = investable
    spent = 0.0
    for r in rows:
        affordable = False
        if r["status"] != "owning" and r["verdict"] in ("buy", "watch"):
            price = r["cost_jpy"] or 0.0
            if r["period"] != "onetime":
                price = (r["monthly_cost"] or 0.0) * 12  # サブスクは年額で予算消費とみなす
            if spent + price <= budget:
                spent += price
                affordable = True
        r["within_budget"] = affordable
    return {"candidates": rows, "budget": _r(budget), "earmarked": _r(spent)}


def compute_finance(session: Session) -> dict[str, Any]:
    reb = compute_rebalance(session)
    roi = compute_roi_ranking(session, reb["investable"] or 0.0, reb["wage_jpy_per_h"] or 2000.0)
    return {"rebalance": reb, "roi": roi}

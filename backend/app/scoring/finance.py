"""資産リバランス + 購入ROIランキング。2つのスプレッドシートの判断ロジックを移植。

- リバランス: 総資産(MoneyForward 転記)から生活防衛資金を引いた余剰を、目標配分へ。
  各バケットの「あといくら投資できる(目標額−現在)」と売買シグナルを出す。
- ROI: 各候補の ROI=(月削減時間×時給 + 月収益)/ 純月コスト を、活用率で重み付け(活用率×ROI)
  してランキング。余剰資金の範囲で上位から「検討」を提示。継続/解約も判定。
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health import AssetHolding, CashflowTx, FinanceState, RoiCandidate
from app.scoring.timewindow import app_today


def _r(v: float | None, n: int = 0) -> float | None:
    return None if v is None else round(float(v), n)


def get_state(session: Session) -> FinanceState:
    st = session.get(FinanceState, 1)
    if st is None:
        st = FinanceState(id=1)
        session.add(st)
        session.flush()
    # 旧 DB に後付けした列は既存行で NULL になりうるので補正。
    if st.reserve_months is None:
        st.reserve_months = 6
    if st.reserve_jpy is None:
        st.reserve_jpy = 0.0
    if st.wage_jpy_per_h is None:
        st.wage_jpy_per_h = 2000.0
    if st.risk_tolerance is None:
        st.risk_tolerance = 3
    return st


RISK_TIERS = {
    0: "現金・預金",
    1: "債券・保守的積立",
    2: "株式・投信(NISA等)",
    3: "仮想通貨(主要)",
    4: "仮想通貨(アルト)・高ボラ",
}
# 許容度 1(保守)〜7(積極)→ 各分岐で安全側に回す比率。
SAFE_RATIO_BY_TOLERANCE = {1: 0.90, 2: 0.80, 3: 0.70, 4: 0.60, 5: 0.50, 6: 0.40, 7: 0.30}

_TIER_KEYWORDS = [
    (4, ["アテンション", "トークン", "token", "bat", "アルト", "xrp", "リップル",
         "doge", "sol", "ソラナ", "ada", "shib", "meme"]),
    (3, ["ビットコイン", "bitcoin", "btc", "イーサ", "ethereum", "eth", "仮想通貨", "暗号資産"]),
    (2, ["nisa", "投信", "投資信託", "emaxis", "s&p", "sp500", "株", "etf", "インデックス",
         "ファンド", "証券", "オルカン", "全世界"]),
    (1, ["定期", "債券", "国債", "積立"]),
]


def classify_risk_tier(name: str) -> int:
    """口座/銘柄名からリスク階層(0=現金 … 4=高ボラ)を自動判定。既定は現金(0)。"""
    n = (name or "").lower()
    for tier, kws in _TIER_KEYWORDS:
        if any(k.lower() in n for k in kws):
            return tier
    return 0


def _effective_tier(h: AssetHolding) -> int:
    return h.risk_tier if h.risk_tier is not None else classify_risk_tier(h.name)


def auto_allocate(holdings: list[AssetHolding], tolerance: int) -> dict[int, float]:
    """リスク階層を安全側から再帰的に分割し、各資産の目標ウェイト(合計100)を返す。

    例(安全比率0.7): 現金70% → 残り30%を 株:暗号=7:3 → 暗号内も主要:アルト=7:3 …
    階層内は現在残高比で按分(残高0なら均等)。
    """
    safe = SAFE_RATIO_BY_TOLERANCE.get(tolerance, 0.70)
    by_tier: dict[int, list[AssetHolding]] = {}
    for h in holdings:
        by_tier.setdefault(_effective_tier(h), []).append(h)
    tiers = sorted(by_tier)
    weights: dict[int, float] = {}
    remaining = 1.0
    for i, tier in enumerate(tiers):
        alloc = remaining if i == len(tiers) - 1 else safe * remaining
        remaining -= alloc
        members = by_tier[tier]
        tot = sum(max(0.0, m.value_jpy) for m in members)
        for m in members:
            share = (max(0.0, m.value_jpy) / tot) if tot > 0 else 1.0 / len(members)
            weights[m.id] = round(alloc * share * 100, 3)
    return weights


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
        tier = _effective_tier(h)
        rows.append({
            "id": h.id, "name": h.name, "category": h.category,
            "value_jpy": _r(h.value_jpy), "target_weight": h.target_weight,
            "target_value": _r(target_value), "room": _r(room),
            "current_ratio": _r(h.value_jpy / total * 100, 1) if total else None,
            "target_ratio": _r(h.target_weight / sum_w * 100, 1) if h.target_weight > 0 else None,
            "signal": signal, "note": h.note,
            "risk_tier": tier, "risk_label": RISK_TIERS.get(tier, ""),
            "risk_overridden": h.risk_tier is not None,
        })
    rows.sort(key=lambda r: (r["room"] is None, -(r["room"] or 0)))
    return {
        "total": _r(total), "reserve": _r(reserve), "investable": _r(investable),
        "invested_now": _r(invested_now),
        "unallocated": _r(max(0.0, investable - invested_now)),  # 余剰のうち未配分=投資余地
        "holdings": rows,
        "wage_jpy_per_h": _r(st.wage_jpy_per_h),
        "risk_tolerance": st.risk_tolerance,
        "risk_tiers": RISK_TIERS,
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


def compute_cashflow(session: Session, total_assets: float = 0.0) -> dict[str, Any]:
    """入出金履歴から月支出/収入・カテゴリ別・推奨防衛資金・ランウェイを算出。"""
    st = get_state(session)
    txs = list(
        session.execute(
            select(CashflowTx).where(CashflowTx.counted.is_(True), CashflowTx.is_transfer.is_(False))
        ).scalars()
    )
    if not txs:
        return {"has_data": False, "reserve_months": st.reserve_months}

    by_month_exp: dict[str, float] = defaultdict(float)
    by_month_inc: dict[str, float] = defaultdict(float)
    by_cat: dict[str, float] = defaultdict(float)
    today = app_today()
    cur_ym = f"{today.year:04d}-{today.month:02d}"
    # 直近6ヶ月のカテゴリ集計用の下限(おおよそ)
    cat_lo = today.year * 12 + today.month - 6
    for t in txs:
        ym = f"{t.date.year:04d}-{t.date.month:02d}"
        if t.amount_jpy < 0:
            by_month_exp[ym] += -t.amount_jpy
            if (t.date.year * 12 + t.date.month) >= cat_lo:
                by_cat[t.major_category or "未分類"] += -t.amount_jpy
        else:
            by_month_inc[ym] += t.amount_jpy

    all_months = sorted(set(by_month_exp) | set(by_month_inc))
    months = [
        {"ym": ym, "expense": _r(by_month_exp.get(ym, 0)), "income": _r(by_month_inc.get(ym, 0)),
         "net": _r(by_month_inc.get(ym, 0) - by_month_exp.get(ym, 0))}
        for ym in all_months[-12:]
    ]
    # 平均は当月(部分月)を除く直近6ヶ月。無ければ全体。
    full = [m for m in all_months if m != cur_ym]
    sample = full[-6:] if full else all_months
    avg_exp = sum(by_month_exp.get(m, 0) for m in sample) / len(sample) if sample else 0.0
    avg_inc = sum(by_month_inc.get(m, 0) for m in sample) / len(sample) if sample else 0.0

    suggested_reserve = avg_exp * st.reserve_months
    runway = (total_assets / avg_exp) if avg_exp > 0 else None
    categories = sorted(
        ({"name": k, "amount": _r(v)} for k, v in by_cat.items()), key=lambda c: -(c["amount"] or 0)
    )[:8]
    return {
        "has_data": True,
        "avg_monthly_expense": _r(avg_exp),
        "avg_monthly_income": _r(avg_inc),
        "avg_monthly_net": _r(avg_inc - avg_exp),
        "reserve_months": st.reserve_months,
        "suggested_reserve": _r(suggested_reserve),
        "runway_months": _r(runway, 1) if runway is not None else None,
        "months": months,
        "categories": categories,
        "tx_count": len(txs),
        "_avg_exp": avg_exp,  # 内部用(防衛資金自動設定)
    }


def compute_finance(session: Session) -> dict[str, Any]:
    reb = compute_rebalance(session)
    roi = compute_roi_ranking(session, reb["investable"] or 0.0, reb["wage_jpy_per_h"] or 2000.0)
    cf = compute_cashflow(session, reb["total"] or 0.0)
    cf.pop("_avg_exp", None)
    return {"rebalance": reb, "roi": roi, "cashflow": cf}

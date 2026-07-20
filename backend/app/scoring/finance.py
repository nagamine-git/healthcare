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

from app.config import get_settings
from app.models.health import AssetHolding, CashflowTx, FinanceState, LifeProfile, RoiCandidate
from app.scoring.timewindow import app_today


def _r(v: float | None, n: int = 0) -> float | None:
    return None if v is None else round(float(v), n)


# MoneyForward「予算」スクショの撮影からこの日数以内だけ「新鮮」とみなし実残高を使う。
# それを超えたら (推測で減算して延命するのではなく) 月次平均ベースにフォールバックし、
# 再取込を促す — MoneyForward 自体がリアルタイムの正解を持っているので、古い自前の値を
# 推測で近似するより「取り直してもらう」方が正確かつ実装が単純。
BUDGET_SNAPSHOT_FRESH_DAYS = 3


def budget_snapshot_status(session: Session) -> dict[str, Any]:
    """予算スナップショットの鮮度を判定する。

    Returns:
        {"fresh": bool, "elapsed_days": int|None, "reason": str|None}
        reason は fresh=False の時のみ: "missing" (未取込) | "different_month" (月またぎ) |
        "stale" (鮮度ウィンドウ超過 or 撮影時点の残り日数を使い切った)。
    """
    st = get_state(session)
    if (
        st.budget_captured_at is None
        or st.budget_variable_remaining_jpy is None
        or st.budget_days_remaining is None
    ):
        return {"fresh": False, "elapsed_days": None, "reason": "missing"}
    today = app_today()
    if st.budget_period_month != today.strftime("%Y-%m"):
        return {"fresh": False, "elapsed_days": None, "reason": "different_month"}
    elapsed = (today - st.budget_captured_at.date()).days
    aged_days = st.budget_days_remaining - elapsed
    if elapsed > BUDGET_SNAPSHOT_FRESH_DAYS or aged_days < 1:
        return {"fresh": False, "elapsed_days": elapsed, "reason": "stale"}
    return {"fresh": True, "elapsed_days": elapsed, "reason": None}


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
# 総資産のこの割合未満の残高は端数(投資対象外)。ゴミ残高が配分枠を食う倒錯を防ぐ。
MIN_ALLOC_RATIO = 0.01

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
    """リスク階層を安全側から配分し、各資産の目標ウェイト(合計100)を返す。

    - 階層間: safe·(1-safe)^i を保有階層で正規化。安全側ほど厚く、最下層(高ボラ)が
      残余を丸取りしない(1銘柄しかない端数アルトが不相応な枠を得るのを防ぐ)。
    - 階層内: 現在残高比で按分(残高0なら均等)。
    - 総資産の MIN_ALLOC_RATIO 未満の端数残高は配分対象外(weight 0)。
    例(安全比率0.7, 現金/株/暗号): 生比率 0.7 : 0.21 : 0.063 → 正規化で約72% : 22% : 6%。
    """
    safe = SAFE_RATIO_BY_TOLERANCE.get(tolerance, 0.70)
    total = sum(max(0.0, h.value_jpy) for h in holdings)
    floor = total * MIN_ALLOC_RATIO
    weights: dict[int, float] = {h.id: 0.0 for h in holdings}
    eligible = [h for h in holdings if max(0.0, h.value_jpy) >= floor]
    if not eligible:
        return weights
    by_tier: dict[int, list[AssetHolding]] = {}
    for h in eligible:
        by_tier.setdefault(_effective_tier(h), []).append(h)
    tiers = sorted(by_tier)
    # 階層の生比率(安全側から): safe, safe·(1-safe), safe·(1-safe)^2, … を正規化。
    raw = {tier: safe * ((1.0 - safe) ** i) for i, tier in enumerate(tiers)}
    s = sum(raw.values()) or 1.0
    for tier in tiers:
        alloc = raw[tier] / s
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
    # リスクラダーは「全資産に対する配分」なので、目標額は総資産ベース。
    base = total
    band = max(base * 0.02, 1000.0)

    rows: list[dict[str, Any]] = []
    for h in holdings:
        target_value = base * (h.target_weight / sum_w) if h.target_weight > 0 else None
        room = (target_value - h.value_jpy) if target_value is not None else None
        if room is None:
            signal = "reserve"  # 配分対象外(現金/防衛資金)
        elif room > band:
            signal = "buy"      # 目標まで余地 → 買い増し
        elif room < -band:
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
    # 目標額の多い順(配分対象が上、配分外は下)。
    rows.sort(key=lambda r: (r["target_value"] is None, -(r["target_value"] or 0)))
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
            "monthly_time_saved_h": c.monthly_time_saved_h, "monthly_use_days": c.monthly_use_days,
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


# 固定費とみなすカテゴリのキーワード (major_category に対する部分一致)。
# 家賃・光熱・通信・保険・サブスク・税・教育など「毎月ほぼ一定で発生」する費目。
_FIXED_CAT_KEYWORDS = (
    "家賃", "住居", "住宅", "ローン", "光熱", "電気", "ガス", "水道", "通信", "携帯",
    "スマホ", "ネット", "インターネット", "保険", "サブスク", "定期", "会費", "年会費",
    "税", "住民税", "年金", "教育", "学費", "保育", "習い事",
)


def _is_fixed_cat(name: str | None) -> bool:
    """カテゴリ名が固定費に該当するか (キーワード部分一致)。"""
    if not name:
        return False
    return any(k in name for k in _FIXED_CAT_KEYWORDS)


def compute_cashflow(session: Session, total_assets: float = 0.0) -> dict[str, Any]:
    """入出金履歴から月支出/収入・カテゴリ別・固定/変動費・推奨防衛資金・ランウェイを算出。"""
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
    by_month_fixed: dict[str, float] = defaultdict(float)
    by_month_var: dict[str, float] = defaultdict(float)
    by_cat: dict[str, float] = defaultdict(float)
    today = app_today()
    cur_ym = f"{today.year:04d}-{today.month:02d}"
    # 直近6ヶ月のカテゴリ集計用の下限(おおよそ)
    cat_lo = today.year * 12 + today.month - 6
    for t in txs:
        ym = f"{t.date.year:04d}-{t.date.month:02d}"
        if t.amount_jpy < 0:
            amt = -t.amount_jpy
            by_month_exp[ym] += amt
            if _is_fixed_cat(t.major_category):
                by_month_fixed[ym] += amt
            else:
                by_month_var[ym] += amt
            if (t.date.year * 12 + t.date.month) >= cat_lo:
                by_cat[t.major_category or "未分類"] += amt
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
    avg_fixed = sum(by_month_fixed.get(m, 0) for m in sample) / len(sample) if sample else 0.0
    avg_var = sum(by_month_var.get(m, 0) for m in sample) / len(sample) if sample else 0.0

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
        "avg_monthly_fixed": _r(avg_fixed),      # 固定費 (家賃・光熱・通信・保険・サブスク等)
        "avg_monthly_variable": _r(avg_var),     # 変動費 (裁量支出の母集団)
        "reserve_months": st.reserve_months,
        "suggested_reserve": _r(suggested_reserve),
        "runway_months": _r(runway, 1) if runway is not None else None,
        "months": months,
        "categories": categories,
        "tx_count": len(txs),
        "_avg_exp": avg_exp,  # 内部用(防衛資金自動設定)
    }


def get_life_profile(session: Session) -> LifeProfile:
    lp = session.get(LifeProfile, 1)
    if lp is None:
        lp = LifeProfile(id=1)
        session.add(lp)
        session.flush()
    return lp


def life_profile_to_dict(lp: LifeProfile) -> dict[str, Any]:
    return {
        "partner": lp.partner, "children": lp.children, "dependents": lp.dependents,
        "housing": lp.housing, "housing_cost_jpy": lp.housing_cost_jpy,
        "monthly_income_jpy": lp.monthly_income_jpy, "monthly_expense_jpy": lp.monthly_expense_jpy,
        "income_type": lp.income_type,
        "debt_balance_jpy": lp.debt_balance_jpy, "debt_rate_pct": lp.debt_rate_pct,
        "nisa_monthly_jpy": lp.nisa_monthly_jpy, "ideco_monthly_jpy": lp.ideco_monthly_jpy,
        "note": lp.note,
    }


def compute_advisor(
    session: Session, reb: dict[str, Any], cf: dict[str, Any]
) -> dict[str, Any]:
    """看板指標(総資産×純資産)+ 診断 + 最善手。既存の reb/cf と LifeProfile から組む。"""
    from app.scoring.finance_advisor import AdvisorInputs, build_advisor

    s = get_settings()
    lp = get_life_profile(session)
    has_cf = bool(cf.get("has_data"))
    # 収入・支出は cashflow(CSV) 優先、無ければ profile(スクショ/手動) をフォールバック
    avg_income = cf.get("avg_monthly_income") if has_cf else None
    if not avg_income and lp.monthly_income_jpy:
        avg_income = lp.monthly_income_jpy
    avg_expense = cf.get("avg_monthly_expense") if has_cf else None
    if not avg_expense and lp.monthly_expense_jpy:
        avg_expense = lp.monthly_expense_jpy
    avg_net = cf.get("avg_monthly_net") if has_cf else None
    if avg_net is None and avg_income is not None and avg_expense is not None:
        avg_net = avg_income - avg_expense
    # 既に NISA を使っているか: 積立設定 or 保有名に NISA を含む (誤って「NISAを始める」を出さない)
    has_nisa = bool(lp.nisa_monthly_jpy and lp.nisa_monthly_jpy > 0) or any(
        "NISA" in (h.get("name") or "").upper() for h in (reb.get("holdings") or [])
    )
    inp = AdvisorInputs(
        gross=reb.get("total") or 0.0,
        debt=lp.debt_balance_jpy or 0.0,
        debt_rate_pct=lp.debt_rate_pct,
        avg_income=avg_income,
        avg_expense=avg_expense,
        avg_net=avg_net,
        unallocated=reb.get("unallocated") or 0.0,
        reserve=reb.get("reserve") or 0.0,
        suggested_reserve=cf.get("suggested_reserve") if has_cf else None,
        housing_cost=lp.housing_cost_jpy,
        nisa_monthly=lp.nisa_monthly_jpy,
        ideco_monthly=lp.ideco_monthly_jpy,
        has_nisa=has_nisa,
    )
    return build_advisor(
        inp,
        good_rate=s.finance_good_debt_max_rate,
        bad_rate=s.finance_bad_debt_min_rate,
        min_savings_rate=s.finance_min_savings_rate,
        housing_burden_ratio=s.finance_housing_burden_ratio,
    )


def compute_finance(session: Session) -> dict[str, Any]:
    reb = compute_rebalance(session)
    roi = compute_roi_ranking(session, reb["investable"] or 0.0, reb["wage_jpy_per_h"] or 2000.0)
    cf = compute_cashflow(session, reb["total"] or 0.0)
    cf.pop("_avg_exp", None)
    advisor = compute_advisor(session, reb, cf)
    profile = life_profile_to_dict(get_life_profile(session))
    return {"rebalance": reb, "roi": roi, "cashflow": cf, "advisor": advisor, "profile": profile}

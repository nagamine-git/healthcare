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

from app.config import get_settings
from app.models.health import CorporateFinanceSnapshot
from app.scoring.achievement import upper_achievement


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

    actionable_expense_ytd_jpy は top 5 に切る前の全費目から集計する (裁量経費の
    1日あたりペース = 衝動買い閾値の分子。上位5件だけだと小さい費目が漏れて過小になる)。
    """
    revenue = operating_income = cogs = None
    items: list[dict[str, Any]] = []
    for b in trial_pl.get("balances") or []:
        cat = b.get("account_category_name")
        # 売上原価は hierarchy_level 2 の合計行 (売上総損益金額の子)。粗利率の算出に要る。
        if b.get("total_line") and cat == "売上原価" and b.get("hierarchy_level") == 2:
            cogs = b.get("closing_balance")
        if b.get("total_line") and b.get("hierarchy_level") == 1:
            if cat == "売上高":
                revenue = b.get("closing_balance")
            elif cat == "営業損益金額":
                operating_income = b.get("closing_balance")
        if not b.get("total_line") and cat == "販売管理費" and b.get("account_item_name"):
            items.append({"name": b["account_item_name"], "amount": b.get("closing_balance")})
    actionable = [
        x["amount"] for x in items
        if x["name"] not in _NON_ACTIONABLE_EXPENSE_CATEGORIES and x["amount"]
    ]
    items.sort(key=lambda x: -(x["amount"] or 0))
    return {
        "revenue_jpy": revenue,
        "operating_income_jpy": operating_income,
        "cogs_jpy": cogs,
        "top_expense_categories": items[:_TOP_EXPENSE_LIMIT],
        "actionable_expense_ytd_jpy": sum(actionable) if actionable else None,
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

# 「経費を見直す」を具体的な費目名に変える時、対象から外す科目。
# 租税公課/法定福利費/支払利息は法的義務でビジネス判断で削れない。減価償却費は非現金の
# 会計上の配分で実際の支出タイミングとは無関係。役員報酬は定期同額給与の縛りがあり、
# 期中に変更すると損金不算入になるため事実上「今すぐ削れる」対象ではない。
_NON_ACTIONABLE_EXPENSE_CATEGORIES = frozenset({
    "租税公課", "法定福利費", "支払利息", "減価償却費", "役員報酬",
})


def _pick_actionable_expense(categories: list[dict[str, Any]]) -> dict[str, Any] | None:
    """税・社会保険・役員報酬等を除いた、実際に削減判断ができる最大の費目。"""
    for c in categories:
        if c.get("name") not in _NON_ACTIONABLE_EXPENSE_CATEGORIES:
            return c
    return None


def _impulse_hold(latest: CorporateFinanceSnapshot) -> tuple[int, str]:
    """法人版の衝動買い保留の閾値 (円, 根拠ラベル)。個人の 1日あたり裁量費と同じ発想:

    裁量経費 (税・社会保険・役員報酬等を除いた販管費) の期首からの累計 ÷ 経過日数 =
    「1日あたり裁量経費」。1日分を超える経費の即決は一晩保留にする (24h ルール)。
    費目内訳か期首日が未取込なら設定の既定値にフォールバックする。
    """
    total = latest.actionable_expense_ytd_jpy
    start = latest.fiscal_start_date
    if total and total > 0 and start is not None:
        days = (latest.date - start).days + 1  # 期首当日を1日目と数える
        if days >= 1:
            return (
                max(500, round(total / days)),
                f"裁量経費(税・役員報酬等を除く販管費){round(total):,}円 ÷ 期首から{days}日",
            )
    return get_settings().corporate_impulse_hold_jpy, "既定値 (freee費目内訳/会計期間 未取込)"


def _breakdown(latest: CorporateFinanceSnapshot) -> dict[str, Any] | None:
    """赤字を「収入を増やす」「支出を減らす」の 2 経路に分解し、各々の必要量を出す。

    「赤字だから頑張る」では動けないので、**同じ赤字を埋めるのに各経路で
    いくら必要か**を並べて、どちらが現実的かを比較できるようにする。

    - 収入経路: 増やした売上のうち利益として残るのは粗利率ぶんだけ。
      よって必要増収 = 赤字 ÷ 粗利率 (粗利率 100% と誤認すると過小評価になる)。
    - 支出経路: 削れるのは裁量経費だけ (税・社保・役員報酬・減価償却は除く)。
      よって必要削減率 = 赤字 ÷ 裁量経費。100% を超えるなら**支出だけでは埋まらない**。

    黒字なら None (埋めるべき赤字が無い)。
    """
    net_income = latest.ytd_net_income_jpy
    if net_income is None or net_income >= 0:
        return None
    deficit = -net_income

    revenue = latest.revenue_jpy
    cogs = latest.cogs_jpy
    gross_margin = None
    if revenue and revenue > 0 and cogs is not None:
        gross_margin = (revenue - cogs) / revenue

    revenue_path: dict[str, Any] = {"required_increase_jpy": None, "gross_margin_pct": None}
    if gross_margin and gross_margin > 0:
        need = deficit / gross_margin
        revenue_path = {
            "required_increase_jpy": _r(need),
            "gross_margin_pct": round(gross_margin * 100, 1),
            "vs_current_pct": round(need / revenue * 100) if revenue else None,
        }

    actionable = latest.actionable_expense_ytd_jpy
    expense_path: dict[str, Any] = {"actionable_total_jpy": _r(actionable), "items": []}
    if actionable and actionable > 0:
        cut_pct = deficit / actionable * 100
        expense_path["required_cut_pct"] = round(cut_pct, 1)
        # 支出だけで埋まらないなら、その事実を隠さず持ち上げる。
        expense_path["enough_alone"] = cut_pct <= 100
        items = []
        for c in latest.top_expense_categories or []:
            name, amount = c.get("name"), c.get("amount") or 0
            if name in _NON_ACTIONABLE_EXPENSE_CATEGORIES or amount <= 0:
                continue
            # この費目を全部消したら赤字の何 % が埋まるか。
            items.append({
                "name": name, "amount": _r(amount),
                "covers_pct": round(amount / deficit * 100, 1),
            })
        expense_path["items"] = items

    return {"deficit_jpy": _r(deficit), "revenue_path": revenue_path, "expense_path": expense_path}


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


GOAL_STRETCH_POINTS = 10.0  # 個人の finance_advisor と同じ: 目標 = 現在スコア + この点数


def _months_elapsed(latest: CorporateFinanceSnapshot) -> float | None:
    """期首からの経過月数。trial_pl の累計値を月次ペースに割り戻す分母。"""
    if latest.fiscal_start_date is None:
        return None
    days = (latest.date - latest.fiscal_start_date).days + 1
    return days / 30.4375 if days >= 1 else None


def _monthly_burn(latest: CorporateFinanceSnapshot) -> float | None:
    """1ヶ月あたりの営業費用。営業損益 = 売上 − 費用 なので 費用 = 売上 − 営業損益。

    freee は月次の費用合計を直接くれないため、期首からの累計を経過月数で割り戻す。
    """
    months = _months_elapsed(latest)
    if months is None or months <= 0:
        return None
    if latest.revenue_jpy is None or latest.operating_income_jpy is None:
        return None
    expense_ytd = latest.revenue_jpy - latest.operating_income_jpy
    return expense_ytd / months if expense_ytd > 0 else None


def _health(latest: CorporateFinanceSnapshot, wealth_index: float | None) -> dict[str, Any]:
    """財務健全度 = 「規模」「持続力」「安全性」の 3 指標を達成度化して平均する。

    1 指標だけ良くても健全とは言えないので、性質の違う 3 つを等重みで見る:
      - 規模   = √(総資産×純資産)。1 つの数字で「大きさ」と「借金の少なさ」を同時に見る
      - 持続力 = ランウェイ (現金 ÷ 月あたり営業費用)
      - 安全性 = 自己資本比率 (純資産 ÷ 総資産)
    取れない指標は平均から外す (0 点扱いにすると未取込が「悪い」に化けるため)。
    """
    s = get_settings()
    burn = _monthly_burn(latest)
    cash = latest.cash_jpy
    runway_months = cash / burn if burn and burn > 0 and cash is not None else None

    gross = latest.total_assets_jpy
    net = latest.net_assets_jpy
    equity_ratio_pct = (net / gross * 100.0) if gross and gross > 0 and net is not None else None

    parts: dict[str, float | None] = {
        "scale": (
            upper_achievement(wealth_index, 0.0, s.finance_corporate_wealth_index_target_jpy)
            if wealth_index is not None else None
        ),
        "runway": (
            upper_achievement(runway_months, s.finance_corporate_runway_floor_months,
                              s.finance_corporate_runway_good_months)
            if runway_months is not None else None
        ),
        "equity": (
            upper_achievement(equity_ratio_pct, s.finance_corporate_equity_ratio_floor_pct,
                              s.finance_corporate_equity_ratio_good_pct)
            if equity_ratio_pct is not None else None
        ),
    }
    got = [v for v in parts.values() if v is not None]
    score = round(sum(got) / len(got), 1) if got else None
    return {
        "runway_months": round(runway_months, 1) if runway_months is not None else None,
        "monthly_burn_jpy": _r(burn),
        "equity_ratio_pct": round(equity_ratio_pct, 1) if equity_ratio_pct is not None else None,
        "subscores": {k: (round(v, 1) if v is not None else None) for k, v in parts.items()},
        "health_score": score,
        "health_goal": min(100.0, score + GOAL_STRETCH_POINTS) if score is not None else None,
    }


def compute_corporate_finance(
    session: Session, *, wealth_index_target: float | None = None,
) -> dict[str, Any] | None:
    """最新スナップショット + 「なんで増えない/減ってる」診断 + 優先順位つき最善手。

    個人の finance_advisor.build_advisor と同じ設計 (看板=√(総資産×純資産) のマイルストーン
    達成度をスコア化、目標=スコア+10点、診断、moves を priority 降順で返す)。
    取込がまだ無ければ None。
    """
    target = (
        wealth_index_target if wealth_index_target is not None
        else get_settings().finance_corporate_wealth_index_target_jpy
    )
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

    # 看板の「数字」は √(総資産×純資産) (個人の finance_advisor と同じ考え方)。
    wealth_index = (gross * net_assets) ** 0.5 if gross > 0 and net_assets and net_assets > 0 else None
    score = upper_achievement(wealth_index, 0.0, target) if wealth_index is not None else None
    goal = min(100.0, score + GOAL_STRETCH_POINTS) if score is not None else None

    diagnosis: list[dict[str, Any]] = []
    moves: list[dict[str, Any]] = []

    if insolvent:
        diagnosis.append({
            "key": "insolvent",
            "text": f"純資産がマイナス ({_r(net_assets):,}円)。債務超過の状態",
        })
        moves.append({
            "priority": 95, "kind": "capital",
            "text": f"純資産{_r(net_assets):,}円のマイナス。資本増強か負債圧縮を最優先で検討する",
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
            "text": f"借入{_r(debt):,}円(純資産の{ratio:.1f}倍)の返済ペースを上げるか借り換えを検討する",
            "why": "高レバレッジは金利上昇や業績悪化時の耐性を弱める",
        })

    top_expenses = latest.top_expense_categories or []
    revenue = latest.revenue_jpy

    if latest.ytd_net_income_jpy is not None and latest.ytd_net_income_jpy < 0:
        diagnosis.append({
            "key": "deficit",
            "text": f"今期は赤字進行中 (当期純損益 {_r(latest.ytd_net_income_jpy):,}円)。"
                    "売上を増やすか経費を見直す",
        })
        actionable = _pick_actionable_expense(top_expenses)
        if actionable:
            a_amount = actionable.get("amount") or 0
            pct = f"、売上の{a_amount / revenue * 100:.0f}%" if revenue else ""
            moves.append({
                "priority": 75, "kind": "deficit",
                "text": f"「{actionable['name']}」({_r(a_amount):,.0f}円{pct}) の契約・使い方を見直す",
                "why": "税・社会保険・役員報酬等の固定費目を除くと、削減インパクトが最も大きい費目",
            })
        else:
            moves.append({
                "priority": 75, "kind": "deficit",
                "text": f"当期純損益 {_r(latest.ytd_net_income_jpy):,}円の赤字。"
                        "売上を増やすか固定費(人件費・外注費等)を見直す",
                "why": "当期純損益がマイナスのままだと純資産は毎期削られ続ける",
            })

    # 費目の集中: 「赤字です」で終わらせず、どの費目が主因かまで言う。
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
                "text": f"前回の同期より純資産が{_r(net_assets_change):,}円減っている。"
                        "支出の急増が無いか確認する",
                "why": "トレンドが下向きだと構造的な問題を見逃している可能性がある",
            })

    moves.sort(key=lambda m: -m["priority"])

    # 衝動買い保留の閾値は個人 (/api/finance) と同じく常時公開 — ウィジェットが
    # 「¥○○以上の経費は一晩保留に」を出すのに使う。moves の優先度には依存させない。
    impulse_hold_jpy, impulse_hold_basis = _impulse_hold(latest)
    health = _health(latest, wealth_index)

    return {
        **health,
        "breakdown": _breakdown(latest),
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
        "wealth_index": wealth_index,
        "score": score,
        "goal": goal,
        "leverage": leverage,
        "diagnosis": diagnosis,
        "moves": moves,
        "net_assets_change_jpy": _r(net_assets_change),
        "impulse_hold_jpy": impulse_hold_jpy,
        "impulse_hold_basis": impulse_hold_basis,
    }

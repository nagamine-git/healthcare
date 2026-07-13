"""資産の「最善手」アドバイザー。

看板指標 = 総資産 × 純資産(= gross × (gross − 負債))。純資産だけでなく「借りられる力
(信用)」も価値、という発想を数式化したもの。会計的には 総資産×純資産 = 純資産² + 負債×純資産。
ただし DuPont(ROE=ROA+(ROA−i)·D/E)より、借金は「金利 i を超えて稼ぐ資産」に使うときだけ良い。
そこで良い借金=低利 / 悪い借金=高利 を色分けし、不良レバレッジを罰する。

「なんで増えないか」を診断し(貯蓄率・現金ドラッグ・住居費・良い/悪い借金・防衛資金)、
今の最善手を優先順位つきで返す。LLM は使わない(決定論・瞬時・説明可能。next_action と同流儀)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 既定閾値(config.py の personal 値。DB ラッパが settings から上書きして渡す)
GOOD_DEBT_MAX_RATE = 3.0     # %以下=低利=良い借金候補
BAD_DEBT_MIN_RATE = 7.0      # %以上=高利=悪い借金(先に返済)
MIN_SAVINGS_RATE = 0.15      # 貯蓄率の下限目安
HOUSING_BURDEN_RATIO = 0.30  # 住居費/収入 が重い閾値


@dataclass
class AdvisorInputs:
    gross: float = 0.0                    # 総資産 (AssetHolding 合計)
    debt: float = 0.0                     # 負債残高
    debt_rate_pct: float | None = None    # 加重平均金利
    avg_income: float | None = None       # 月収 (cashflow 優先 / profile 補完)
    avg_expense: float | None = None
    avg_net: float | None = None          # 月の純額 (= 貯蓄)
    unallocated: float = 0.0              # 未投資の余剰現金 (現金ドラッグ)
    reserve: float = 0.0
    suggested_reserve: float | None = None
    housing_cost: float | None = None     # 月の家賃 or ローン返済
    nisa_monthly: float | None = None
    ideco_monthly: float | None = None
    has_nisa: bool = False                 # 既に NISA を使っているか (保有 or 積立設定)


def _man(v: float | None) -> str:
    """円 → 読みやすい万円表記。"""
    if v is None:
        return "―"
    if abs(v) >= 10_000:
        return f"{v / 10_000:.0f}万円"
    return f"{round(v):,}円"


def _leverage(debt: float, rate: float | None, good_rate: float, bad_rate: float) -> str:
    if debt <= 0:
        return "none"
    if rate is None:
        return "caution"  # 金利不明はレバレッジの良否を判定できない
    if rate <= good_rate:
        return "good"
    if rate >= bad_rate:
        return "bad"
    return "caution"


def build_advisor(
    inp: AdvisorInputs,
    *,
    good_rate: float = GOOD_DEBT_MAX_RATE,
    bad_rate: float = BAD_DEBT_MIN_RATE,
    min_savings_rate: float = MIN_SAVINGS_RATE,
    housing_burden_ratio: float = HOUSING_BURDEN_RATIO,
) -> dict[str, Any]:
    """看板指標 + 診断 + 優先順位つき最善手を返す純関数。"""
    gross = inp.gross
    debt = inp.debt
    net = gross - debt
    leverage = _leverage(debt, inp.debt_rate_pct, good_rate, bad_rate)
    has_data = gross > 0 or debt > 0 or inp.avg_income is not None

    base: dict[str, Any] = {
        "gross": gross, "debt": debt, "net": net,
        "headline": gross * net, "leverage": leverage,
        "has_data": has_data, "diagnosis": [], "moves": [],
    }
    if not has_data:
        return base

    diagnosis: list[dict[str, Any]] = []
    moves: list[dict[str, Any]] = []

    # 貯蓄率
    savings_rate: float | None = None
    if inp.avg_income and inp.avg_income > 0 and inp.avg_net is not None:
        savings_rate = inp.avg_net / inp.avg_income
        if savings_rate < min_savings_rate:
            if inp.avg_net <= 0:
                diagnosis.append({"key": "savings_rate", "level": "warn",
                                  "text": f"毎月ほぼ残っていない(貯蓄率 {savings_rate * 100:.0f}%)。"
                                          "資産が増えない最大の主因はここ"})
            else:
                diagnosis.append({"key": "savings_rate", "level": "warn",
                                  "text": f"貯蓄率 {savings_rate * 100:.0f}% — 収入 {_man(inp.avg_income)} に対し"
                                          f"月 {_man(inp.avg_net)} しか残らない。増えない主因"})

    # 現金ドラッグ(防衛資金超の未投資現金)
    if inp.unallocated > 0:
        diagnosis.append({"key": "cash_drag", "level": "warn",
                          "text": f"余剰現金 {_man(inp.unallocated)} が投資されず眠っている(現金ドラッグ)。"
                                  "現金は増えない"})

    # 住居費負担
    if inp.avg_income and inp.avg_income > 0 and inp.housing_cost is not None:
        ratio = inp.housing_cost / inp.avg_income
        if ratio > housing_burden_ratio:
            diagnosis.append({"key": "housing_burden", "level": "warn",
                              "text": f"住居費が収入の {ratio * 100:.0f}% "
                                      f"({housing_burden_ratio * 100:.0f}%超は重い)"})

    # 悪い借金
    if leverage == "bad":
        diagnosis.append({"key": "bad_debt", "level": "warn",
                          "text": f"高利の借金 {inp.debt_rate_pct:.1f}% が純資産を毎年削っている"})

    # 防衛資金不足
    reserve_gap = 0.0
    if inp.suggested_reserve is not None and inp.reserve < inp.suggested_reserve:
        reserve_gap = inp.suggested_reserve - inp.reserve
        diagnosis.append({"key": "reserve_gap", "level": "info",
                          "text": f"生活防衛資金が {_man(reserve_gap)} 不足"})

    # --- 最善手(priority 降順) ---
    if leverage == "bad":
        r = inp.debt_rate_pct or 0.0
        moves.append({"priority": 95, "kind": "debt",
                      "text": f"高利の借金({r:.1f}%)を最優先で返す",
                      "why": f"返済は確実に {r:.1f}% のリターン。どんな投資より確実で無リスク"})
    if reserve_gap > 0:
        moves.append({"priority": 85, "kind": "reserve",
                      "text": f"生活防衛資金 {_man(reserve_gap)} を先に確保",
                      "why": "不測時に投資を取り崩さない土台。ここが攻めの前提"})
    if inp.unallocated > 0:
        moves.append({"priority": 75, "kind": "invest",
                      "text": f"余剰現金 {_man(inp.unallocated)} を NISA/インデックスへ",
                      "why": "現金は増えない。低コスト分散で複利に乗せるのが王道"})
    using_nisa = inp.has_nisa or bool(inp.nisa_monthly and inp.nisa_monthly > 0)
    if not using_nisa:
        moves.append({"priority": 70, "kind": "tax",
                      "text": "NISA枠を活用する(未設定なら毎月の積立を開始)",
                      "why": "運用益が非課税になるだけでリターンが底上げされる"})
    if savings_rate is not None and savings_rate < min_savings_rate:
        moves.append({"priority": 60, "kind": "savings",
                      "text": "固定費(特に住居費)を見直し貯蓄率を上げる",
                      "why": "貯蓄率は投資リターンより効く最大のレバー"})
    if debt > 0 and leverage == "good":
        moves.append({"priority": 40, "kind": "credit",
                      "text": "低利ローンは繰上げ返済を急がない(信用枠=借りられる力を保つ)",
                      "why": "金利 < 期待リターンなら手元資金を投資に回す方が有利。信用は選択肢"})

    moves.sort(key=lambda m: -m["priority"])
    base["diagnosis"] = diagnosis
    base["moves"] = moves
    return base

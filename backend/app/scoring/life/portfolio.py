"""人生ポートフォリオ: 資産運用の「目標配分 × 現在比率 × ROI × リバランス」を人生ドメインへ。

時間・エネルギーを投資資本、各資本(ドメイン)を保有銘柄とみなす。
- 目標配分 = 重要度ウェイト(人生ゴール由来)。
- 現在配分 = 直近の行動(GoodActionLog)が実際どこに向いたか。
- ROI(次の一手の期待リターン) = 重要度 × 伸びしろ(100-現状) × 出遅れ度。
- シグナル = 投資(buy)/維持(hold)/足りてる(funded)/寄せ過ぎ(trim)。
"""

from __future__ import annotations

from collections import Counter
from datetime import date as date_type
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health import GoodActionLog
from app.scoring.life.tree import CAPITAL_ACTION_KINDS, compute_life_tree
from app.scoring.timewindow import jst_window_start


def _r(v: float | None, n: int = 1) -> float | None:
    return None if v is None else round(float(v), n)


def compute_portfolio(session: Session, target: date_type, window_days: int = 14) -> dict[str, Any]:
    tree = compute_life_tree(session, target)
    caps = tree["capitals"]
    total_weight = sum(c["weight"] for c in caps) or 1.0

    # 直近 window の行動を資本に割り当て、現在配分(実際にどこへ投資したか)を出す。
    kind_to_cap = {k: cap for cap, kinds in CAPITAL_ACTION_KINDS.items() for k in kinds}
    lo = jst_window_start(window_days, target)
    rows = session.execute(
        select(GoodActionLog.kind).where(GoodActionLog.ts >= lo)
    ).scalars().all()
    counts = Counter(kind_to_cap[k] for k in rows if k in kind_to_cap)
    total_effort = sum(counts.values())

    holdings: list[dict[str, Any]] = []
    for c in caps:
        w = float(c["weight"])
        target_alloc = w / total_weight * 100.0
        current_alloc = (counts.get(c["key"], 0) / total_effort * 100.0) if total_effort else 0.0
        level = c.get("achievement")
        gap = max(0.0, 100.0 - (level if level is not None else 0.0))
        under = max(0.0, target_alloc - current_alloc)
        roi = w * (gap / 100.0) * (1.0 + under / max(target_alloc, 1.0))
        breach = bool(c.get("breach"))
        if breach or (current_alloc < target_alloc * 0.7 and gap > 15):
            signal = "buy"          # 出遅れ × 伸びしろ大(または最低ライン割れ)→ 投資
        elif level is not None and level >= 80 and current_alloc >= target_alloc * 0.8:
            signal = "funded"       # 高水準で配分も足りている → 追加不要
        elif current_alloc > target_alloc * 1.4:
            signal = "trim"         # 重要度に対して寄せ過ぎ → 他へ回す
        else:
            signal = "hold"
        holdings.append({
            "key": c["key"], "label": c["label"], "weight": w,
            "target_alloc": _r(target_alloc), "current_alloc": _r(current_alloc),
            "level": _r(level), "gap": _r(gap), "roi": round(roi, 4),
            "signal": signal, "breach": breach,
            "kinds": c.get("kinds", []),
        })

    holdings.sort(key=lambda h: h["roi"], reverse=True)
    max_roi = max((h["roi"] for h in holdings), default=0.0) or 1.0
    for h in holdings:
        h["roi_rel"] = round(h["roi"] / max_roi * 100.0, 1)  # 0-100(レーダー/バー用)

    top = next((h for h in holdings if h["signal"] == "buy"), holdings[0] if holdings else None)
    return {
        "holdings": holdings,
        "top_pick": top,
        "total_effort": total_effort,
        "window_days": window_days,
        "goal": tree.get("goal"),
    }

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

from app.models.health import DailyScore, GoodActionLog
from app.scoring.life.tree import CAPITAL_ACTION_KINDS, compute_life_tree
from app.scoring.timewindow import jst_window_start


def _r(v: float | None, n: int = 1) -> float | None:
    return None if v is None else round(float(v), n)


def investment_mode(session: Session, target: date_type) -> dict[str, Any]:
    """資本余力(個人版ランウェイ/充足率)から「いま攻めるか守るか」を判定。

    資産運用シートの「ランウェイが短い・充足率が低い時は投資を控える」を、個人の
    エネルギー・回復状態へ適用。コンディション/睡眠/自律神経/エネルギー + 重大アラートで判断。
    """
    score = session.execute(
        select(DailyScore).where(DailyScore.date <= target).order_by(DailyScore.date.desc()).limit(1)
    ).scalars().first()
    total = score.total if score else None
    sleep = score.sleep_sub if score else None
    hrv = score.hrv_sub if score else None
    bb = score.bb_sub if score else None
    capacity = total
    if capacity is None:
        vals = [v for v in (sleep, hrv, bb) if v is not None]
        capacity = sum(vals) / len(vals) if vals else None

    from app.scoring.profile import resolve_profile
    from app.scoring.wellbeing_alerts import evaluate_alerts

    prof = resolve_profile()
    bmi_floor = round(18.5 * (prof.height_cm / 100) ** 2, 1)
    try:
        alerts = evaluate_alerts(
            session, target, target_weight_kg=prof.target_weight_kg, weight_lower_kg=bmi_floor
        )
    except Exception:
        alerts = []
    crit = [a for a in alerts if a.severity == "critical"]
    warn = [a for a in alerts if a.severity == "warning"]

    reasons: list[str] = []
    if sleep is not None and sleep < 50:
        reasons.append("睡眠が不足")
    if hrv is not None and hrv < 40:
        reasons.append("自律神経が低下")
    if bb is not None and bb < 40:
        reasons.append("エネルギーが低い")
    reasons += [a.title for a in crit[:2]]

    if crit or (capacity is not None and capacity < 45):
        mode = "defense"   # 守り: 新規投資を控え回復へ
    elif capacity is not None and capacity >= 70 and not warn:
        mode = "offense"   # 攻め: 余力あり、高ROIに投資
    else:
        mode = "neutral"
    return {
        "mode": mode,
        "capacity": _r(capacity, 0),
        "reasons": reasons,
        "alerts": len(crit) + len(warn),
    }


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

    roi_top = next((h for h in holdings if h["signal"] == "buy"), holdings[0] if holdings else None)
    mode = investment_mode(session, target)

    # 投資モードで「次の一手」を出し分け(攻め=高ROIへ / 守り=回復へ)。
    body = next((h for h in holdings if h["key"] == "body"), None)
    if mode["mode"] == "defense":
        top = body or roi_top
        directive = "守り — 新規投資を控え、睡眠・回復に資本(時間/気力)を回す時期"
    elif mode["mode"] == "offense":
        top = roi_top
        directive = "攻め — 余力あり。高ROIの領域に投資を寄せる好機"
    else:
        top = roi_top
        directive = "中立 — 維持しつつ、出遅れの領域へ少し投資"

    return {
        "holdings": holdings,
        "top_pick": top,
        "directive": directive,
        "mode": mode["mode"],
        "capacity": mode["capacity"],
        "mode_reasons": mode["reasons"],
        "total_effort": total_effort,
        "window_days": window_days,
        "goal": tree.get("goal"),
    }

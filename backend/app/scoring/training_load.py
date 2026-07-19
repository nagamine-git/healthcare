"""実績ベースの負荷提案 (double progression) — LLM の目視漸進をシステム算出に置き換える。

材料: Garmin 筋トレの raw_json (summarizedExerciseSets: category/subCategory/maxWeight[g]/reps) と
直近の LLM 処方 (LlmComment.payload.actions[].exercises)。無い種目は
settings.user_starting_weights × training_level 係数で初期値を出す。
"""

from __future__ import annotations

import re
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

AVAILABLE_DUMBBELLS = [2.0, 4.0, 8.0, 12.0, 16.0, 20.0]  # 手持ち (中間なし)
LEVEL_FACTOR = {"beginner": 1.0, "intermediate": 1.25, "advanced": 1.5}
_TARGET_REPS = 10        # double progression の上限 rep
_PROGRESS_SESSIONS = 2   # 同重量でこれだけ達成したら昇量
_OVERSHOOT_REPS = 15     # 目標を大幅超過 (=軽すぎ)。1セッションでも即昇量する閾値
_DELOAD_DAYS = 7
_BW_HARD_REPS = 20       # 自重でこれ超えたら難種目へ移行

# Garmin の種目 enum (category/subCategory) → 日本語ラベル。LLM 処方と突き合わせる。
_EXERCISE_LABELS = {
    "ROMANIAN_DEADLIFT": "ルーマニアンデッドリフト", "DEADLIFT": "デッドリフト",
    "BENCH_PRESS": "ベンチプレス", "DUMBBELL_BENCH_PRESS": "ダンベルベンチプレス",
    "INCLINE_BENCH_PRESS": "インクラインベンチプレス",
    "SHOULDER_PRESS": "ショルダープレス", "OVERHEAD_PRESS": "ショルダープレス",
    "DUMBBELL_SHOULDER_PRESS": "ダンベルショルダープレス",
    "PUSH_UP": "腕立て", "DIAMOND_PUSH_UP": "ダイヤモンド腕立て",
    "ROW": "ローイング", "BENT_OVER_ROW": "ローイング", "DUMBBELL_ROW": "ダンベルロー",
    "SQUAT": "スクワット", "GOBLET_SQUAT": "ゴブレットスクワット",
    "BULGARIAN_SPLIT_SQUAT": "ブルガリアンスクワット", "LUNGE": "ランジ",
    "BICEP_CURL": "カール", "CURL": "カール", "HAMMER_CURL": "ハンマーカール",
    "KNEELING_AB_WHEEL": "アブローラー", "AB_WHEEL": "アブローラー",
    "LATERAL_RAISE": "サイドレイズ", "PLANK": "プランク",
    "CALF_RAISE": "カーフレイズ", "HIP_THRUST": "ヒップスラスト",
}


def _label_for(category: Any, sub_category: Any) -> str | None:
    for key in (sub_category, category):
        k = str(key or "").upper()
        if k in _EXERCISE_LABELS:
            return _EXERCISE_LABELS[k]
    raw = str(sub_category or category or "").replace("_", " ").title().strip()
    return raw or None


def _parse_sets(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Garmin raw_json の summarizedExerciseSets を [{label, weight_kg, reps}] に。

    maxWeight は **グラム**単位 (8000=8kg)。0/欠損は自重として weight_kg=0 で残す
    (自重も回数で漸進を追うため、以前のように捨てない)。
    """
    out: list[dict[str, Any]] = []
    for st in raw.get("summarizedExerciseSets") or []:
        label = _label_for(st.get("category"), st.get("subCategory"))
        reps = int(st.get("reps") or 0)
        if not label or reps <= 0:
            continue
        mw = st.get("maxWeight")
        weight_kg = round(float(mw) / 1000.0, 1) if mw else 0.0
        out.append({"label": label, "weight_kg": weight_kg, "reps": reps})
    return out


def _next_weight(w: float) -> float:
    for cand in AVAILABLE_DUMBBELLS:
        if cand > w + 0.01:
            return cand
    return w


def _prev_weight(w: float) -> float:
    prev = [c for c in AVAILABLE_DUMBBELLS if c < w - 0.01]
    return prev[-1] if prev else w


def _parse_weight(s: str | float | None) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"([\d.]+)\s*kg", str(s))
    return float(m.group(1)) if m else None


def suggest_for_exercise(
    *, history: list[dict[str, Any]], today: date_type,
    starting_weight: float | None, level: str = "beginner",
) -> dict[str, Any]:
    """history: [{date, weight_kg, reps}] 新しい順。決定論的に次回を提案する。"""
    if not history:
        base = (starting_weight or AVAILABLE_DUMBBELLS[1]) * LEVEL_FACTOR.get(level, 1.0)
        w = max((c for c in AVAILABLE_DUMBBELLS if c <= base), default=AVAILABLE_DUMBBELLS[0])
        return {"suggested_weight_kg": w, "suggested_reps": "8-10", "basis": "初回 (レベル基準)"}
    last = history[0]
    lw = float(last["weight_kg"])
    days_gap = (today - last["date"]).days
    # 自重 (weight 0): 重量でなく回数で漸進。据え置きを許さない (ぬるま湯回避)
    if lw == 0:
        lr = int(last.get("reps") or 0)
        if lr >= _BW_HARD_REPS:
            return {
                "suggested_weight_kg": 0.0, "suggested_reps": f"{lr}+",
                "basis": f"自重{lr}回 — 難種目/加重へ変更 (片脚・デクライン・リュック加重)",
            }
        return {
            "suggested_weight_kg": 0.0, "suggested_reps": f"{lr + 2}以上",
            "basis": f"前回{lr}回 → +2回で漸進 (自重は回数を伸ばす)",
        }
    if days_gap > _DELOAD_DAYS:
        return {
            "suggested_weight_kg": _prev_weight(lw), "suggested_reps": "10-12",
            "basis": f"{days_gap}日空き — deload (-1段階) で再開",
        }
    # 大幅超過 (目標の 1.5 倍以上 = 明確に軽すぎ): 1 セッションでも即昇量する。
    # これが無いと「8kg×23回」でも据え置きになり、達成不能な低 RIR 指示 (RIR2@8-10) を招く。
    last_reps = int(last.get("reps") or 0)
    if last_reps >= _OVERSHOOT_REPS:
        nw = _next_weight(lw)
        if nw > lw:
            return {
                "suggested_weight_kg": nw, "suggested_reps": "8-10",
                "basis": f"{lw:g}kg×{last_reps}rep (目標 {_TARGET_REPS} を大幅超過) — 軽すぎるため即昇量",
            }
        return {
            "suggested_weight_kg": lw, "suggested_reps": f"{last_reps}+",
            "basis": f"{lw:g}kg×{last_reps}rep だが手持ち最大 — 片手/テンポ/難種目で強度を上げる",
        }
    # 同重量で目標rep以上を何セッション達成したか
    hits = 0
    for h in history:
        if abs(float(h["weight_kg"]) - lw) < 0.01 and int(h.get("reps") or 0) >= _TARGET_REPS:
            hits += 1
        else:
            break
    if hits >= _PROGRESS_SESSIONS:
        nw = _next_weight(lw)
        if nw > lw:
            return {
                "suggested_weight_kg": nw, "suggested_reps": "6-8",
                "basis": f"{lw:g}kg×{_TARGET_REPS}rep を {hits}回達成 — 昇量",
            }
    return {
        "suggested_weight_kg": lw, "suggested_reps": f"{_TARGET_REPS}目標",
        "basis": "同重量で rep を積む (double progression)",
    }


def _garmin_history(target: date_type, days: int = 42) -> dict[str, list[dict[str, Any]]]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Workout

    since = datetime.combine(target - timedelta(days=days), datetime.min.time())
    out: dict[str, list[dict[str, Any]]] = {}
    with session_scope() as s:
        rows = s.execute(
            select(Workout).where(Workout.start >= since).order_by(Workout.start.desc())
        ).scalars().all()
        for w in rows:
            d = (w.start + timedelta(hours=9)).date()
            for st in _parse_sets(w.raw_json or {}):
                out.setdefault(st["label"], []).append(
                    {"date": d, "weight_kg": st["weight_kg"], "reps": st["reps"]}
                )
    return out


def gather_load_suggestions(target: date_type) -> dict[str, Any]:
    """助言 payload 用: 種目別の直近実績+システム算出の次回負荷。"""
    from app.config import get_settings

    s = get_settings()
    level = getattr(s, "training_level", "beginner")
    starting = {}
    for k, v in (s.user_starting_weights or {}).items():
        pw = _parse_weight(v)
        if pw is not None:
            starting[k] = pw
    hist = _garmin_history(target)
    suggestions: dict[str, Any] = {}
    keys = set(hist) | set(starting)
    for key in sorted(keys):
        h = hist.get(key, [])
        sug = suggest_for_exercise(
            history=h, today=target, starting_weight=starting.get(key), level=level
        )
        if h:
            sug["last"] = {
                "date": h[0]["date"].isoformat(),
                "weight_kg": h[0]["weight_kg"], "reps": h[0]["reps"],
            }
        suggestions[key] = sug
    return {"level": level, "available_dumbbells_kg": AVAILABLE_DUMBBELLS, "exercises": suggestions}

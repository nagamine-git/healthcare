"""Life Optimization OS のドメイン木(Layer 2)の算出。

MECE な capital(資本/状態)ごとに達成度 0-100 を出し、目標由来の重点ウェイトで
life_score を合成、維持フロア割れを検出する。capital 達成度は既存シグナルを再利用。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import DomainWeight, GardenDaily, Goal
from app.scoring import domains
from app.scoring.achievement import upper_achievement
from app.scoring.identity.store import build_gap_report

# MECE な capital とその葉(フェーズ1は葉はラベルのみ)。
LIFE_TREE: list[dict] = [
    {"key": "body", "label": "身体資本", "leaves": ["睡眠", "運動", "栄養", "体組成", "回復"]},
    {"key": "mind", "label": "精神状態", "leaves": ["ストレス・情動", "内省"]},
    {"key": "intellect", "label": "知的資本", "leaves": ["学習", "読書", "作品インプット"]},
    {"key": "creation", "label": "創造・仕事", "leaves": ["制作・コーディング", "ディープワーク", "発信"]},
    {"key": "relationships", "label": "関係資本", "leaves": ["家族", "友人・人脈"]},
    {"key": "economy", "label": "経済資本", "leaves": ["家計", "投資・資産"]},
]

# capital → 達成度を頻度から測る garden 行動種別(body は health サブで別計算)。
CAPITAL_KINDS: dict[str, list[str]] = {
    "mind": ["meditation", "journaling", "reflection", "gratitude"],
    "intellect": ["reading", "learning"],
    "creation": ["coding", "creative", "deepwork"],
    "relationships": ["social", "family"],
    "economy": ["finance"],
}


def aggregate_tree(
    achievements: dict[str, float | None],
    weights: dict[str, float],
    floors: dict[str, float],
) -> dict:
    """capital 達成度・重み・フロアから木・life_score・breach を組む(純関数)。"""
    capitals = []
    num = den = 0.0
    breaches: list[str] = []
    for node in LIFE_TREE:
        k = node["key"]
        a = achievements.get(k)
        w = weights.get(k, 1.0)
        fl = floors.get(k, 0.0)
        breach = a is not None and a < fl
        if breach:
            breaches.append(k)
        if a is not None:
            num += w * a
            den += w
        capitals.append({
            "key": k, "label": node["label"], "achievement": a,
            "weight": w, "floor": fl, "breach": breach, "leaves": node["leaves"],
        })
    life_score = round(num / den, 1) if den > 0 else None
    focus_capital = max(capitals, key=lambda c: c["weight"])["key"] if capitals else None
    return {
        "capitals": capitals,
        "life_score": life_score,
        "focus_capital": focus_capital,
        "breaches": breaches,
    }


def freq_achievement(
    session: Session, kinds: list[str], target: date, window: int, target_days: int
) -> float:
    """直近 window 日で当該 kind が観測された日数 / target_days の upper 達成度。"""
    start = target - timedelta(days=window - 1)
    rows = (
        session.query(GardenDaily)
        .filter(GardenDaily.date >= start, GardenDaily.date <= target)
        .all()
    )
    kindset = set(kinds)
    days = sum(1 for r in rows if r.contributions and (kindset & set(r.contributions.keys())))
    return round(upper_achievement(days, 0.0, float(target_days)), 1)


def active_goal(session: Session) -> dict:
    """active な Goal を返す。無ければ config 既定から seed して返す。"""
    row = session.query(Goal).filter(Goal.active.is_(True)).order_by(Goal.id.desc()).first()
    if row is None:
        default = get_settings().life_default_goal
        row = Goal(
            title=default["title"], horizon=default.get("horizon"),
            capital_weights=default["capital_weights"], active=True,
        )
        session.add(row)
        session.flush()
    return {
        "id": row.id, "title": row.title, "horizon": row.horizon,
        "capital_weights": row.capital_weights or {},
    }


def compute_life_tree(session: Session, target: date) -> dict:
    s = get_settings()
    win, tgt = s.life_freq_window_days, s.life_freq_target_days
    achievements: dict[str, float | None] = {
        "body": domains.health_achievement(target),
        "mind": freq_achievement(session, CAPITAL_KINDS["mind"], target, win, tgt),
        "intellect": freq_achievement(session, CAPITAL_KINDS["intellect"], target, win, tgt),
        "creation": freq_achievement(session, CAPITAL_KINDS["creation"], target, win, tgt),
        "relationships": freq_achievement(session, CAPITAL_KINDS["relationships"], target, win, tgt),
        "economy": freq_achievement(session, CAPITAL_KINDS["economy"], target, win, tgt),
    }
    goal = active_goal(session)
    weights = dict(goal["capital_weights"])
    for dw in session.query(DomainWeight).all():
        if dw.domain in weights:
            weights[dw.domain] = dw.weight

    tree = aggregate_tree(achievements, weights, s.life_capital_floors)

    report = build_gap_report(session)
    purpose = {
        "overall": report.get("overall"),
        "layers": report.get("layers"),
        "archetype_name": report.get("archetype_name"),
    }
    return {
        "purpose": purpose,
        "goal": goal,
        **tree,
        "generated_at": datetime.utcnow().isoformat(),
    }

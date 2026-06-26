"""Life Optimization OS のドメイン木(Layer 2)の算出。

MECE な capital(資本/状態)を葉(leaf)単位の達成度に分解して算出し、capital へロールアップ。
目標由来の重点ウェイトで life_score を合成、維持フロア割れを検出する。
達成度は既存シグナル(健康サブスコア / garden 行動頻度 / Compass)を再利用。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import DailyScore, DomainWeight, GardenDaily, Goal, MediaLog
from app.scoring.achievement import upper_achievement
from app.scoring.identity.store import build_gap_report

# capital → そこに効く garden 行動種別(最適配分の提案で使う)。
CAPITAL_ACTION_KINDS: dict[str, list[str]] = {
    "body": ["aerobic", "strength", "sleep", "steps", "nature", "healthy_meal"],
    "mind": ["meditation", "journaling", "reflection", "gratitude"],
    "intellect": ["reading", "learning"],
    "creation": ["coding", "creative", "deepwork"],
    "relationships": ["social", "family"],
    "economy": ["finance"],
}

# ドメイン相互関係(辺): from が上がると to にも効く、を一言で。
DOMAIN_EDGES: list[dict] = [
    {"from": "body", "to": ["mind", "intellect", "creation"], "note": "睡眠・運動は心/知/創すべての土台"},
    {"from": "mind", "to": ["creation", "relationships"], "note": "整った心が良い仕事と関係を生む"},
    {"from": "economy", "to": ["mind"], "note": "経済基盤の安定が不安を減らす"},
]

# MECE な capital と葉。各葉は signal(達成度の出し方)を持つ。
# signal: "score:<field>" = DailyScore 由来 / "garden:k1,k2" = 行動頻度 / "none" = 未計測(null)
LIFE_TREE: list[dict] = [
    {"key": "body", "label": "身体資本", "leaves": [
        {"label": "睡眠", "signal": "score:sleep"},
        {"label": "運動", "signal": "garden:aerobic,strength"},
        {"label": "栄養", "signal": "garden:healthy_meal"},
        {"label": "体組成", "signal": "score:bodycomp"},
        {"label": "回復(自律神経)", "signal": "score:recovery"},
    ]},
    {"key": "mind", "label": "精神状態", "leaves": [
        {"label": "ストレス・情動", "signal": "none"},
        {"label": "内省", "signal": "garden:meditation,journaling,reflection,gratitude"},
    ]},
    {"key": "intellect", "label": "知的資本", "leaves": [
        {"label": "学習", "signal": "garden:learning"},
        {"label": "読書", "signal": "garden:reading"},
        {"label": "作品インプット", "signal": "media"},
    ]},
    {"key": "creation", "label": "創造・仕事", "leaves": [
        {"label": "制作・コーディング", "signal": "garden:coding"},
        {"label": "ディープワーク", "signal": "garden:deepwork"},
        {"label": "発信", "signal": "garden:creative"},
    ]},
    {"key": "relationships", "label": "関係資本", "leaves": [
        {"label": "家族", "signal": "garden:family"},
        {"label": "友人・人脈", "signal": "garden:social"},
    ]},
    {"key": "economy", "label": "経済資本", "leaves": [
        {"label": "家計", "signal": "garden:finance"},
        {"label": "投資・資産", "signal": "none"},
    ]},
]


def _mean(vals: list[float]) -> float | None:
    present = [v for v in vals if v is not None]
    return round(sum(present) / len(present), 1) if present else None


def aggregate_tree(
    capitals_in: list[dict],
    weights: dict[str, float],
    floors: dict[str, float],
) -> dict:
    """capital(達成度・葉つき)・重み・フロアから木・life_score・breach を組む(純関数)。

    capitals_in: [{key, label, achievement, leaves:[{label, achievement}]}]
    """
    capitals = []
    num = den = 0.0
    breaches: list[str] = []
    for node in capitals_in:
        k = node["key"]
        a = node["achievement"]
        w = weights.get(k, 1.0)
        fl = floors.get(k, 0.0)
        breach = a is not None and a < fl
        if breach:
            breaches.append(k)
        if a is not None:
            num += w * a
            den += w
        capitals.append({**node, "weight": w, "floor": fl, "breach": breach})
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


def _leaf_achievement(
    session: Session, signal: str, target: date, window: int, target_days: int,
    score: DailyScore | None,
) -> float | None:
    if signal == "none":
        return None
    if signal.startswith("score:"):
        if score is None:
            return None
        field = signal.split(":", 1)[1]
        if field == "sleep":
            return score.sleep_sub
        if field == "recovery":
            return _mean([score.hrv_sub, score.bb_sub])
        if field == "bodycomp":
            return _mean([score.weight_sub, score.body_fat_sub])
        return None
    if signal.startswith("garden:"):
        kinds = signal.split(":", 1)[1].split(",")
        return freq_achievement(session, kinds, target, window, target_days)
    if signal == "media":
        # 直近 window 日で観た作品数 → 目標 2 本で 100%(Compass の作品インプット)
        start = target - timedelta(days=window - 1)
        seen = (
            session.query(MediaLog)
            .filter(
                MediaLog.status == "seen",
                MediaLog.seen_at.isnot(None),
                MediaLog.seen_at >= datetime(start.year, start.month, start.day),
            )
            .count()
        )
        return round(upper_achievement(float(seen), 0.0, 2.0), 1)
    return None


def recommend_allocation(capitals: list[dict], weights: dict[str, float]) -> list[dict]:
    """今日エネルギーを効かせるべき領域を優先度順に提案(純関数)。

    優先度: フロア割れ(最低ライン)を最優先、次に 重み×伸びしろ。
    未計測(achievement=None)は「始めてみる」として中位。
    """
    scored = []
    for c in capitals:
        a = c["achievement"]
        w = weights.get(c["key"], 1.0)
        if c.get("breach"):
            priority = 1000 + w * (100 - (a or 0))
            reason = "最低ラインを下回っている(まず立て直す)"
        elif a is None:
            priority = w * 50
            reason = "まだ記録がない(始めてみる)"
        else:
            priority = w * (100 - a)
            reason = "重点 × 伸びしろが大きい" if w >= 1.5 else "伸びしろがある"
        scored.append({
            "capital": c["key"], "label": c["label"], "reason": reason,
            "kinds": CAPITAL_ACTION_KINDS.get(c["key"], []), "_p": priority,
        })
    scored.sort(key=lambda x: x["_p"], reverse=True)
    return [{k: v for k, v in s.items() if k != "_p"} for s in scored[:3]]


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
    score = session.get(DailyScore, target)

    capitals_in = []
    for node in LIFE_TREE:
        leaves = []
        for leaf in node["leaves"]:
            a = _leaf_achievement(session, leaf["signal"], target, win, tgt, score)
            leaves.append({"label": leaf["label"], "achievement": a})
        capital_ach = _mean([leaf["achievement"] for leaf in leaves])
        capitals_in.append({
            "key": node["key"], "label": node["label"],
            "achievement": capital_ach, "leaves": leaves,
        })

    goal = active_goal(session)
    weights = dict(goal["capital_weights"])
    for dw in session.query(DomainWeight).all():
        if dw.domain in weights:
            weights[dw.domain] = dw.weight

    tree = aggregate_tree(capitals_in, weights, s.life_capital_floors)

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
        "allocation": recommend_allocation(tree["capitals"], weights),
        "edges": DOMAIN_EDGES,
        "generated_at": datetime.utcnow().isoformat(),
    }

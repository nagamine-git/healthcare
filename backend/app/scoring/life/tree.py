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
    "body": ["aerobic", "strength", "sleep", "steps", "nature", "healthy_meal", "mobility"],
    "mind": ["meditation", "journaling", "reflection", "gratitude", "music", "breathwork",
             "digital_detox", "tidying", "planning"],
    "intellect": ["reading", "learning", "cultural_input"],
    "creation": ["coding", "creative", "deepwork"],
    "relationships": ["social", "family", "teaching"],
    "economy": ["finance"],
}

# ドメイン相互関係(辺): from が上がると to にも効く、を一言で。
DOMAIN_EDGES: list[dict] = [
    {"from": "body", "to": ["mind", "intellect", "creation"], "note": "睡眠・運動は心/知/創すべての土台"},
    {"from": "mind", "to": ["creation", "relationships"], "note": "整った心が良い仕事と関係を生む"},
    {"from": "economy", "to": ["mind"], "note": "経済基盤の安定が不安を減らす"},
]

# MECE な capital と葉。各葉は signal(達成度の出し方)を持つ。
# signal: "atlas:<key>" = 全体マップの実データ score(0-100)/ "score:<field>" = DailyScore 由来
#         "garden:k1,k2" = 行動頻度(自己申告)/ "media" = 作品インプット / "none" = 未計測(null)
# 実センサー/実データがある葉は atlas: を優先(全体マップと同じ現実を映す)。
# 行動系(内省・発信・関係など)はセンサーが無いため garden: のまま。
LIFE_TREE: list[dict] = [
    {"key": "body", "label": "身体資本", "leaves": [
        {"label": "睡眠", "signal": "atlas:sleep"},
        {"label": "運動(負荷)", "signal": "atlas:load"},
        {"label": "体力(測定)", "signal": "atlas:fitness"},
        {"label": "栄養", "signal": "garden:healthy_meal"},
        {"label": "体組成", "signal": "atlas:body"},
        {"label": "回復(自律神経)", "signal": "atlas:hrv"},
    ]},
    {"key": "mind", "label": "精神状態", "leaves": [
        {"label": "心の健康 (PHQ-4)", "signal": "mental"},
        {"label": "デジタル節制 (Airgap)", "signal": "atlas:airgap"},
        {"label": "内省", "signal": "garden:meditation,journaling,reflection,gratitude"},
    ]},
    {"key": "intellect", "label": "知的資本", "leaves": [
        {"label": "学習", "signal": "atlas:learning"},
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
        {"label": "純資産(資産形成)", "signal": "atlas:wealth_index"},
        {"label": "家計(貯蓄率)", "signal": "atlas:savings_rate"},
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
) -> float | None:
    """直近 window 日で当該 kind が観測された日数 / target_days の upper 達成度。

    窓内に庭ログが1件も無ければ「未計測」(None)を返す。自己申告の行動頻度は
    "記録なし=やっていない" ではないため、0(サボり/要立て直し)と区別する。
    庭ログはあるが当該 kind が無い場合のみ 0.0(記録した上でやっていない=実データ)。
    """
    start = target - timedelta(days=window - 1)
    rows = (
        session.query(GardenDaily)
        .filter(GardenDaily.date >= start, GardenDaily.date <= target)
        .all()
    )
    logged = [r for r in rows if r.contributions]
    if not logged:
        return None
    kindset = set(kinds)
    days = sum(1 for r in logged if kindset & set(r.contributions.keys()))
    return round(upper_achievement(days, 0.0, float(target_days)), 1)


def flatten_atlas_scores(node: dict) -> dict[str, float | None]:
    """全体マップ(atlas)ツリーを {key: score(0-100)} に平坦化(純関数)。

    目的・領域の葉は、この実データ score を `atlas:<key>` シグナルで参照する。
    """
    out: dict[str, float | None] = {node["key"]: node.get("score")}
    for c in node.get("children", []):
        out.update(flatten_atlas_scores(c))
    return out


def leaf_achievement(
    session: Session, signal: str, target: date, window: int, target_days: int,
    score: DailyScore | None, atlas_scores: dict[str, float | None] | None = None,
) -> float | None:
    if signal == "none":
        return None
    if signal == "mental":
        # 直近14日の PHQ-4 を苦痛度→達成度に反転 (未実施は未計測)。
        from app.scoring.mental import distress_achievement, latest_screening
        row = latest_screening(session, target, within_days=14)
        return distress_achievement(row.phq4 if row else None)
    if signal.startswith("atlas:"):
        # 全体マップの実データ score をそのまま採用(欠測/未知キーは未計測=None)。
        key = signal.split(":", 1)[1]
        return (atlas_scores or {}).get(key)
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

    # 全体マップ(実データ)を1回組んで {key: score} に平坦化。atlas: シグナルの葉が参照する。
    from app.scoring.atlas import build_atlas
    atlas_scores = flatten_atlas_scores(build_atlas(session))

    capitals_in = []
    for node in LIFE_TREE:
        leaves = []
        for leaf in node["leaves"]:
            a = leaf_achievement(session, leaf["signal"], target, win, tgt, score, atlas_scores)
            leaves.append({"label": leaf["label"], "achievement": a})
        capital_ach = _mean([leaf["achievement"] for leaf in leaves])
        capitals_in.append({
            "key": node["key"], "label": node["label"],
            "achievement": capital_ach, "leaves": leaves,
            "kinds": CAPITAL_ACTION_KINDS.get(node["key"], []),
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

"""部位別 (5 機能群) の刺激・回復・週間負荷と「今日やるべき部位」サジェスト。

設計思想 (判断基準: 科学 > 医学 > ミリタリー > 時間効率 > コスト効率):
- 回復は刺激した筋群ごとに 24–48h (大筋群は ~72h) で別々に進む (筋タンパク合成の窓)。
  だから「脚は回復中でも背中は今日やれる」が成立し、部位別に追う意味がある。
- 肥大の最大レバーは筋群あたりの週間ボリューム (Schoenfeld 系メタ解析 週 ~10–20 セット)。
- 「魅力的な肉体」= V字 (肩幅:ウエスト)。中部三角筋と背中 (広背筋) が最重要かつ
  ボクシング/腕立て等のプレス動作では取り残されやすい → 美的重みを高く設定。

データは Garmin の activity (Workout.type=typeKey, training_load) から完全自動で導出する。
新テーブルは持たず、既存 Workout を都度集計する (projection と同じ読み取り専用方式)。

正直な限界:
- シャドーボクシング/タバタ/自重 HIIT は種目情報なしの cardio/HIIT として入るため、
  「引く (背中)」系はほぼ検出できない。これは "刺激記録なし → 伸びしろ" として
  サジェストに出るが、強度は推定不能なので confidence="inferred"/"none" で薄く扱う。
- Garmin 筋トレで種目 (exerciseSets) が記録されていれば、そこから正確な部位を取り
  confidence="measured" に上がる。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import Workout

# 5 機能群。aesthetic = 魅力的な肉体 (V字) への寄与重み、recovery_h = 回復目安 (MPS 窓)。
# home = 在宅・器具なしで実行できる具体アクション (科学的に肥大刺激が入るもの)。
GROUPS: list[dict[str, Any]] = [
    {"key": "shoulders", "label": "肩 (横)", "aesthetic": 1.0, "recovery_h": 48,
     "home": "パイクプッシュアップ / サイドレイズ(水ボトル・リュック)"},
    {"key": "pull", "label": "引く (背中・二頭)", "aesthetic": 0.95, "recovery_h": 48,
     "home": "懸垂(バー) / リュック・タオルでローイング ※器具が要"},
    {"key": "core", "label": "体幹", "aesthetic": 0.7, "recovery_h": 36,
     "home": "プランク / ハンギングレッグレイズ / アブローラー"},
    {"key": "push", "label": "押す (胸・三頭)", "aesthetic": 0.6, "recovery_h": 48,
     "home": "腕立て(ダイヤモンド/デクライン)"},
    {"key": "legs", "label": "脚", "aesthetic": 0.55, "recovery_h": 72,
     "home": "ブルガリアンスクワット / ピストルスクワット / カーフレイズ"},
]
_GROUP_KEYS = [g["key"] for g in GROUPS]

# activity typeKey → 各群の関与度 (0–1)。primary=主働、secondary=補助。
# 未知の typeKey は _FALLBACK_INVOLVE (全身軽め・低信頼) を使う。
_INVOLVE: dict[str, dict[str, float]] = {
    # 格闘技系: 肩(パンチ)・体幹(回旋)・脚(フットワーク)主体。背中は軽い
    "boxing": {"shoulders": 0.8, "core": 0.7, "push": 0.4, "legs": 0.3, "pull": 0.2},
    "kickboxing": {"shoulders": 0.7, "core": 0.7, "push": 0.4, "legs": 0.5, "pull": 0.2},
    "mixed_martial_arts": {"shoulders": 0.7, "core": 0.8, "push": 0.4, "legs": 0.5, "pull": 0.4},
    # 有酸素・脚主体
    "running": {"legs": 1.0, "core": 0.3},
    "treadmill_running": {"legs": 1.0, "core": 0.3},
    "trail_running": {"legs": 1.0, "core": 0.4},
    "track_running": {"legs": 1.0, "core": 0.3},
    "indoor_running": {"legs": 1.0, "core": 0.3},
    "walking": {"legs": 0.6, "core": 0.2},
    "casual_walking": {"legs": 0.5, "core": 0.2},
    "hiking": {"legs": 0.8, "core": 0.3},
    "cycling": {"legs": 1.0, "core": 0.3},
    "road_biking": {"legs": 1.0, "core": 0.3},
    "indoor_cycling": {"legs": 1.0, "core": 0.3},
    "virtual_ride": {"legs": 1.0, "core": 0.3},
    "mountain_biking": {"legs": 1.0, "core": 0.4},
    "elliptical": {"legs": 0.7, "core": 0.3},
    "stair_climbing": {"legs": 0.9, "core": 0.3},
    # 引く系が強い有酸素 (背中の数少ない自動検出源)
    "swimming": {"pull": 0.8, "shoulders": 0.7, "core": 0.5, "legs": 0.4},
    "lap_swimming": {"pull": 0.8, "shoulders": 0.7, "core": 0.5, "legs": 0.4},
    "open_water_swimming": {"pull": 0.8, "shoulders": 0.7, "core": 0.5, "legs": 0.4},
    "rowing": {"pull": 0.9, "legs": 0.6, "core": 0.5, "shoulders": 0.3},
    "indoor_rowing": {"pull": 0.9, "legs": 0.6, "core": 0.5, "shoulders": 0.3},
    # 体幹・柔軟
    "yoga": {"core": 0.7, "legs": 0.4, "shoulders": 0.3},
    "pilates": {"core": 0.8, "legs": 0.4, "shoulders": 0.2},
}
# 全身系 (種目不明)。strength/HIIT で exerciseSets が取れない時のフォールバック。
_WHOLE_BODY = {"push": 0.5, "pull": 0.5, "legs": 0.6, "core": 0.6, "shoulders": 0.4}
_WHOLE_BODY_TYPES = {
    "strength_training", "indoor_cardio", "hiit", "high_intensity_interval_training",
    "bootcamp", "functional_strength", "cardio", "fitness_equipment", "training",
    "crossfit", "tabata",
}
_FALLBACK_INVOLVE = dict.fromkeys(_GROUP_KEYS, 0.3)

# Garmin exerciseSets の category → 群。記録があれば typeKey 推定を上書きし高信頼に。
_CATEGORY_GROUP: list[tuple[str, str]] = [
    ("SHOULDER", "shoulders"), ("LATERAL_RAISE", "shoulders"), ("SHRUG", "shoulders"),
    ("PULL_UP", "pull"), ("CHIN_UP", "pull"), ("ROW", "pull"), ("PULL", "pull"),
    ("LAT", "pull"), ("CURL", "pull"), ("DEADLIFT", "pull"), ("FACE_PULL", "pull"),
    ("BENCH", "push"), ("PUSH_UP", "push"), ("PRESS", "push"), ("CHEST", "push"),
    ("FLY", "push"), ("DIP", "push"), ("TRICEP", "push"), ("PUSH", "push"),
    ("SQUAT", "legs"), ("LUNGE", "legs"), ("LEG", "legs"), ("CALF", "legs"),
    ("HIP", "legs"), ("GLUTE", "legs"), ("HAMSTRING", "legs"),
    ("PLANK", "core"), ("CRUNCH", "core"), ("CORE", "core"), ("AB_", "core"),
    ("SIT_UP", "core"), ("RAISE", "core"), ("ROTATION", "core"), ("CARRY", "core"),
]

_MEANINGFUL = 0.4  # この関与度以上を「刺激あり」とみなす (last_stimulus 判定)
_WINDOW_DAYS = 14  # 集計窓 (週間負荷は直近 7d、刺激は 14d で十分)


def _exercise_groups(raw: Any) -> dict[str, float] | None:
    """Garmin strength activity の exerciseSets から群別関与度を作る (取れなければ None)。"""
    if not isinstance(raw, dict):
        return None
    sets = raw.get("summarizedExerciseSets") or raw.get("fullExerciseSets") or []
    if not isinstance(sets, list) or not sets:
        return None
    involve: dict[str, float] = {}
    for s in sets:
        if not isinstance(s, dict):
            continue
        cat = (s.get("category") or s.get("exerciseCategory") or "")
        cat = str(cat).upper()
        for needle, group in _CATEGORY_GROUP:
            if needle in cat:
                # 同群に複数種目あれば最大 1.0 まで加算
                involve[group] = min(1.0, involve.get(group, 0.0) + 0.6)
                break
    return involve or None


def _involvement(w: Workout) -> tuple[dict[str, float], bool]:
    """workout → (群別関与度, measured?)。measured=True は種目記録由来 (高信頼)。"""
    ex = _exercise_groups(w.raw_json)
    if ex:
        return ex, True
    t = (w.type or "").lower()
    if t in _INVOLVE:
        return _INVOLVE[t], False
    if t in _WHOLE_BODY_TYPES:
        return dict(_WHOLE_BODY), False
    return dict(_FALLBACK_INVOLVE), False


def _load(w: Workout) -> float:
    """workout の負荷量。Garmin training_load が無ければ時間 (分) で代替。"""
    if w.training_load is not None and w.training_load > 0:
        return float(w.training_load)
    if w.duration_s:
        return w.duration_s / 60.0  # 1 分 = 1 負荷ユニットの粗い代替
    return 0.0


def state(*, now: datetime | None = None) -> dict[str, Any]:
    """部位別の刺激・回復・週間負荷 + 今日やるべき部位サジェスト。"""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    win_start = now - timedelta(days=_WINDOW_DAYS)
    week_start = now - timedelta(days=7)

    with session_scope() as session:
        rows = session.execute(
            select(Workout).where(Workout.start >= win_start, Workout.start <= now)
        ).scalars().all()
        works = []
        for w in rows:
            inv, measured = _involvement(w)
            works.append(
                {"start": w.start, "involve": inv, "measured": measured, "load": _load(w)}
            )

    groups: list[dict[str, Any]] = []
    for g in GROUPS:
        key = g["key"]
        last_at: datetime | None = None
        week_load = 0.0
        measured_any = False
        stimulated = False
        for w in works:
            inv = w["involve"].get(key, 0.0)
            if inv <= 0:
                continue
            if inv >= _MEANINGFUL:
                stimulated = True
                if last_at is None or w["start"] > last_at:
                    last_at = w["start"]
                if w["measured"]:
                    measured_any = True
            if w["start"] >= week_start:
                week_load += inv * w["load"]
        hours_since = (now - last_at).total_seconds() / 3600 if last_at else None
        recovery_pct = (
            min(100.0, hours_since / g["recovery_h"] * 100) if hours_since is not None else 100.0
        )
        confidence = "measured" if measured_any else ("inferred" if stimulated else "none")
        groups.append({
            "key": key, "label": g["label"], "aesthetic": g["aesthetic"],
            "home": g["home"], "recovery_h": g["recovery_h"],
            "last_at": last_at.isoformat() if last_at else None,
            "hours_since": round(hours_since, 1) if hours_since is not None else None,
            "recovery_pct": round(recovery_pct),
            "week_load": round(week_load, 1),
            "confidence": confidence,
        })

    # 今日やるべき部位: 美的重み × 回復係数 × 不足係数。
    #   回復係数 — まだ痛い (回復<100) 部位は下げる (科学: 回復窓内の再刺激は非効率)
    #   不足係数 — 直近週の負荷が少ない部位を上げる (週間ボリューム平準化)。
    #            全群中の最大負荷を基準に相対化 (絶対目標を置かず自己校正)
    max_load = max((g["week_load"] for g in groups), default=0.0) or 1.0
    for g in groups:
        rec = g["recovery_pct"] / 100
        deficit = 1 - min(1.0, g["week_load"] / max_load)
        g["priority"] = round(
            g["aesthetic"] * (0.4 + 0.6 * rec) * (0.3 + 0.7 * deficit), 3
        )
    ranked = sorted(groups, key=lambda g: g["priority"], reverse=True)
    # 回復済み (>=60%) の上位を本日のおすすめに。痛い部位は除外
    ready = [g for g in ranked if g["recovery_pct"] >= 60]
    suggestion = [
        {"key": g["key"], "label": g["label"], "home": g["home"],
         "confidence": g["confidence"], "week_load": g["week_load"]}
        for g in (ready or ranked)[:2]
    ]

    any_data = any(g["confidence"] != "none" for g in groups)
    has_measured = any(g["confidence"] == "measured" for g in groups)
    overall_conf = "high" if has_measured else ("low" if any_data else "none")

    return {
        "groups": groups,
        "suggestion": suggestion,
        "confidence": overall_conf,
        "window_days": _WINDOW_DAYS,
    }


def llm_summary(*, now: datetime | None = None) -> dict[str, Any]:
    """LLM コーチング用の部位別サマリ。トレ処方を部位別カードと同一データに揃える。"""
    s = state(now=now)
    return {
        "groups": [
            {
                "key": g["key"], "label": g["label"], "recovery_pct": g["recovery_pct"],
                "week_load": g["week_load"], "confidence": g["confidence"],
            }
            for g in s["groups"]
        ],
        "today_should_train": [{"key": x["key"], "label": x["label"]} for x in s["suggestion"]],
        "note": (
            "Garmin の活動から自動算出。recovery_pct が高い=回復済みで叩ける / 低い=直近に負荷で要回復。"
            "today_should_train は回復済み×直近ボリューム不足×美的重み(肩・背中優先)で選んだ本日の推奨部位。"
            "自重/シャドーボクシング/HIIT は引く(背中)を検出できないため confidence=none で伸びしろ扱い。"
        ),
    }

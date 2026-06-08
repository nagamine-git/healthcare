"""ライフドメイン (自己目標管理) の達成度と統合スコア。

各ドメインは target 日の達成度 (0-100, 高いほど理想に近い) を返す。
- health: 既存トレンド6指標の最新達成度の平均
- meditation: 当日の瞑想分 (mindful_minutes + breathwork) 合計の目標達成度
DB は内部で session_scope を使う (呼び出し側は target 日付だけ渡す)。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as date_type
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import MetricSample

# プリセット (ドメイン -> 重み)。将来ドメイン追加時にここへ追記する。
DOMAIN_WEIGHT_PRESETS: dict[str, dict[str, Any]] = {
    "balanced": {"label": "バランス",
                 "weights": {"health": 1.0, "meditation": 1.0, "speech": 1.0, "learning": 1.0, "work": 1.0}},
    "recovery": {"label": "回復優先",
                 "weights": {"health": 2.0, "meditation": 1.0, "speech": 0.5, "learning": 0.5, "work": 0.5}},
    "mindful": {"label": "内省優先",
                "weights": {"health": 1.0, "meditation": 2.0, "speech": 0.5, "learning": 1.0, "work": 0.5}},
    "deep_work": {"label": "仕事集中",
                  "weights": {"health": 1.0, "meditation": 0.5, "speech": 1.0, "learning": 1.5, "work": 2.0}},
    "speech_focus": {"label": "発話強化",
                     "weights": {"health": 1.0, "meditation": 0.5, "speech": 2.0, "learning": 0.5, "work": 1.0}},
}


def health_achievement(target: date_type) -> float | None:
    """既存トレンド6指標 (sleep/hrv/energy/load/weight/body_fat) の最新達成度の平均。"""
    from app.scoring import achievement as ach
    from app.scoring import trend_sources
    from app.scoring.profile import resolve_profile

    s = resolve_profile()
    bundle = trend_sources.collect_raw_series(target, days=28)
    vals: list[float] = []

    sleep = [r for r in bundle["sleep"] if r[1] is not None]
    if sleep:
        r = sleep[-1]
        a = ach.sleep_achievement(
            total_min=r[1], garmin_sleep_score=r[2],
            deep_min=r[3], rem_min=r[4], light_min=r[5], awake_min=r[6],
        )
        if a is not None:
            vals.append(a)
    if bundle["hrv"]:
        a = ach.hrv_achievement(bundle["hrv"][-1][1], bundle["hrv_baseline"])
        if a is not None:
            vals.append(a)
    if bundle["energy"]:
        a = ach.energy_achievement(bundle["energy"][-1][1])
        if a is not None:
            vals.append(a)
    if bundle["acwr"]:
        a = ach.load_achievement(bundle["acwr"][-1][1])
        if a is not None:
            vals.append(a)
    if bundle["weight"]:
        a = ach.weight_achievement(bundle["weight"][-1][1], s.target_weight_kg)
        if a is not None:
            vals.append(a)
    if bundle["body_fat"]:
        a = ach.body_fat_achievement(
            bundle["body_fat"][-1][1], s.target_body_fat_pct, s.body_fat_tolerance_pct
        )
        if a is not None:
            vals.append(a)

    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def meditation_minutes(target: date_type) -> float | None:
    """当日 (JST) の瞑想分合計。mindful_minutes (HAE) と breathwork ワークアウト
    (garmin) を合算する。計測が1件も無ければ None。"""
    from app.models import Workout
    from app.scoring.timewindow import jst_day_bounds

    start, end = jst_day_bounds(target)
    with session_scope() as session:
        rows = session.execute(
            select(MetricSample.value).where(
                MetricSample.metric_key == "mindful_minutes",
                MetricSample.ts >= start,
                MetricSample.ts < end,
            )
        ).all()
        breath = session.execute(
            select(Workout.duration_s).where(
                Workout.type == "breathwork",
                Workout.start >= start,
                Workout.start < end,
            )
        ).all()
    if not rows and not breath:
        return None
    total = sum(float(r[0]) for r in rows if r[0] is not None)
    total += sum(float(b[0]) / 60.0 for b in breath if b[0] is not None)
    return round(total, 1)


def meditation_achievement(target: date_type) -> float | None:
    from app.scoring import achievement as ach

    total = meditation_minutes(target)
    if total is None:
        return None
    return round(
        ach.upper_achievement(total, 0.0, float(get_settings().meditation_target_min)), 2
    )


def speech_achievement(target: date_type) -> float | None:
    """当日の発話練習サマリ score_overall (0-100 をそのまま達成度として使う)。"""
    from app.models import SpeechSession

    with session_scope() as session:
        row = session.get(SpeechSession, target)
        score = row.score_overall if row else None
    if score is None:
        return None
    return round(float(score), 2)


def _external_achievement(domain_key: str) -> Callable[[date_type], float | None]:
    """ExternalDomainEntry (学習・仕事 等) の当日達成度を返す関数を生成する。"""

    def fn(target: date_type) -> float | None:
        from app.models import ExternalDomainEntry

        with session_scope() as session:
            row = session.get(ExternalDomainEntry, (domain_key, target))
            ach = row.achievement if row else None
        return round(float(ach), 2) if ach is not None else None

    return fn


# ドメイン定義: (key, label, 達成度関数)
LIFE_DOMAINS: list[tuple[str, str, Callable[[date_type], float | None]]] = [
    ("health", "健康", health_achievement),
    ("meditation", "瞑想", meditation_achievement),
    ("speech", "発話力", speech_achievement),
    ("learning", "学習", _external_achievement("learning")),
    ("work", "仕事", _external_achievement("work")),
]

# この日数を超えてデータが無いドメインは「途絶 (stale)」とみなす
STALE_AFTER_DAYS: dict[str, int] = {
    "health": 2, "meditation": 7, "speech": 7, "learning": 7, "work": 7,
}


def _jst_date(ts) -> date_type:
    from datetime import timedelta
    return (ts + timedelta(hours=9)).date()


def domain_last_data(key: str) -> date_type | None:
    """ドメインの最終データ日 (JST)。供給パイプラインの死活監視に使う。

    ソース単位の死活 (source_sync) では「ソースは生きているが特定メトリクスだけ
    停止」(例: HAE は同期成功し続けつつ mindful_minutes だけ途絶) を検出できない
    ため、ドメインが実際に読むデータの最終日を見る。
    """
    from sqlalchemy import func

    from app.models import ExternalDomainEntry, SleepSession, SpeechSession, Workout

    with session_scope() as session:
        if key == "health":
            return session.execute(select(func.max(SleepSession.date))).scalar()
        if key == "meditation":
            mindful_ts = session.execute(
                select(func.max(MetricSample.ts)).where(
                    MetricSample.metric_key == "mindful_minutes")
            ).scalar()
            breath_ts = session.execute(
                select(func.max(Workout.start)).where(Workout.type == "breathwork")
            ).scalar()
            dates = [_jst_date(t) for t in (mindful_ts, breath_ts) if t is not None]
            return max(dates) if dates else None
        if key == "speech":
            return session.execute(select(func.max(SpeechSession.date))).scalar()
        if key in ("learning", "work"):
            return session.execute(
                select(func.max(ExternalDomainEntry.date)).where(
                    ExternalDomainEntry.domain == key)
            ).scalar()
    return None


def compute_life(target: date_type, weights: dict[str, float]) -> dict[str, Any]:
    """各ドメインの期待調整済みスコアとライフスコアを返す。

    重みは期待水準: achievement = min(100, 生達成度 / weight)。
    weight 0.5 なら半分の成果で満点、weight 2.0 なら2倍要求。
    weight=0 のドメインは「今は対象外」として集計から除外 (achievement は生値)。
    ライフスコアは補正後スコアの単純平均 (null と weight=0 は除外)。
    """
    domains: list[dict[str, Any]] = []
    for key, label, fn in LIFE_DOMAINS:
        raw = fn(target)
        weight = float(weights.get(key, 1.0))
        if raw is None:
            adjusted = None
        elif weight > 0:
            adjusted = round(min(100.0, raw / weight), 2)
        else:
            adjusted = raw
        domains.append({
            "key": key,
            "label": label,
            "achievement": adjusted,
            "raw_achievement": raw,
            "weight": weight,
        })
    vals = [d["achievement"] for d in domains
            if d["achievement"] is not None and d["weight"] > 0]
    life_score = round(sum(vals) / len(vals), 2) if vals else None
    return {"life_score": life_score, "domains": domains}

"""習慣ペース予測。

「いまの時刻までに、いつもならどれだけ進んでいるか」を個人の過去データから出し、
今日の実績と比べて遅れていれば促す (例: いつものペースだと水を飲んでるはず → 飲め)。

仕組み: 各日について「現在の時刻 (time-of-day) までの累積」を計算し、過去 N 日の中央値を
「いつもの今頃」= 期待値とする。今日の累積と比べて遅れ/順調/前倒しを判定し、
push 系 (多いほど良い: 水分/歩数/活動) は遅れていれば具体的な一言を出す。
完璧予測ではなく行動ナッジなので、確信度 (履歴日数) も付ける。
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import CaffeineIntake, MetricSample
from app.scoring.timewindow import JST

# 累積する習慣。push=True は「多いほど良い → 遅れたら促す」。
HABITS: list[dict[str, Any]] = [
    {"key": "water", "label": "水分", "metric": "garmin_hydration_ml", "unit": "ml",
     "emoji": "💧", "verb": "1杯 (250ml) 飲もう", "push": True},
    {"key": "steps", "label": "歩数", "metric": "step_count", "unit": "歩",
     "emoji": "👣", "verb": "少し歩こう", "push": True},
    {"key": "active", "label": "活動", "metric": "active_energy", "unit": "kcal",
     "emoji": "🔥", "verb": "体を動かそう", "push": True},
    {"key": "caffeine", "label": "カフェイン", "metric": "__caffeine__", "unit": "mg",
     "emoji": "☕", "verb": "", "push": False},  # info のみ (飲み過ぎを促さない)
]

_HISTORY_DAYS = 28
_MIN_DAYS = 5       # これ未満は判定しない
_BEHIND = 0.6       # 期待比これ未満で「遅れ」
_AHEAD = 1.3        # これ超で「前倒し」


def _now_jst() -> datetime:
    return datetime.now(JST).replace(tzinfo=None)


def _cumulative_by_time(metric: str, now_jst: datetime) -> tuple[float | None, int, float]:
    """(期待値=過去日の同時刻までの累積の中央値, 履歴日数, 今日の同時刻までの実績)。"""
    cutoff_sec = now_jst.hour * 3600 + now_jst.minute * 60
    today = now_jst.date()
    start_date = today - timedelta(days=_HISTORY_DAYS)
    # UTC 窓 (JST 日付に丸めるため広めに)
    lo = datetime.combine(start_date - timedelta(days=1), datetime.min.time())
    hi = datetime.combine(today + timedelta(days=1), datetime.min.time())

    with session_scope() as s:
        if metric == "__caffeine__":
            rows = s.execute(
                select(CaffeineIntake.ts, CaffeineIntake.mg)
                .where(CaffeineIntake.ts >= lo, CaffeineIntake.ts < hi)
            ).all()
        else:
            rows = s.execute(
                select(MetricSample.ts, MetricSample.value)
                .where(MetricSample.metric_key == metric, MetricSample.ts >= lo, MetricSample.ts < hi)
            ).all()

    per_day: dict[Any, float] = {}
    today_actual = 0.0
    for ts, v in rows:
        if v is None:
            continue
        jst = ts + timedelta(hours=9)
        sec = jst.hour * 3600 + jst.minute * 60
        if sec > cutoff_sec:  # 現在の時刻より後の分は除外 (同時刻までの累積)
            continue
        d = jst.date()
        if d == today:
            today_actual += float(v)
        elif d >= start_date:
            per_day[d] = per_day.get(d, 0.0) + float(v)

    vals = list(per_day.values())
    expected = statistics.median(vals) if vals else None
    return expected, len(vals), today_actual


def intraday_profile(
    metric: str, ref_date: Any, *, days: int = _HISTORY_DAYS, step_h: float = 0.5
) -> list[dict[str, float]]:
    """終日の「いつもの累積カーブ」。各時刻 (hour-of-day) での過去 days 日の累積中央値。

    タイムラインに「いつものペース」線を重ねるための予測カーブ。[{h: 時刻, v: 累積}]。
    """
    from collections import defaultdict

    start_date = ref_date - timedelta(days=days)
    lo = datetime.combine(start_date - timedelta(days=1), datetime.min.time())
    hi = datetime.combine(ref_date, datetime.min.time())  # 今日は除く (履歴のみ)

    with session_scope() as s:
        if metric == "__caffeine__":
            rows = s.execute(
                select(CaffeineIntake.ts, CaffeineIntake.mg)
                .where(CaffeineIntake.ts >= lo, CaffeineIntake.ts < hi)
            ).all()
        else:
            rows = s.execute(
                select(MetricSample.ts, MetricSample.value)
                .where(MetricSample.metric_key == metric, MetricSample.ts >= lo, MetricSample.ts < hi)
            ).all()

    by_day: dict[Any, list[tuple[float, float]]] = defaultdict(list)
    for ts, v in rows:
        if v is None:
            continue
        jst = ts + timedelta(hours=9)
        if jst.date() < start_date:
            continue
        by_day[jst.date()].append((jst.hour + jst.minute / 60, float(v)))

    if len(by_day) < _MIN_DAYS:
        return []
    marks = [i * step_h for i in range(int(24 / step_h) + 1)]
    profile: list[dict[str, float]] = []
    for m in marks:
        day_vals = [sum(val for hod, val in lst if hod <= m) for lst in by_day.values()]
        profile.append({"h": round(m, 2), "v": round(statistics.median(day_vals), 1)})
    return profile


def state(*, now_jst: datetime | None = None) -> dict[str, Any]:
    now_jst = now_jst or _now_jst()
    habits: list[dict[str, Any]] = []
    for h in HABITS:
        expected, n, actual = _cumulative_by_time(h["metric"], now_jst)
        item: dict[str, Any] = {
            "key": h["key"], "label": h["label"], "unit": h["unit"], "emoji": h["emoji"],
            "expected": round(expected) if expected is not None else None,
            "actual": round(actual), "n": n, "status": "no_data", "nudge": None,
            "pct": None, "confidence": "low",
        }
        if expected is not None and n >= _MIN_DAYS and expected > 0:
            pct = actual / expected
            item["pct"] = round(pct, 2)
            item["confidence"] = "high" if n >= 14 else ("medium" if n >= 7 else "low")
            if h["push"]:
                if pct < _BEHIND:
                    item["status"] = "behind"
                    item["nudge"] = (
                        f"{h['emoji']} いつもは今頃 {round(expected)}{h['unit']}。"
                        f"まだ {round(actual)}{h['unit']} — {h['verb']}！"
                    )
                elif pct > _AHEAD:
                    item["status"] = "ahead"
                else:
                    item["status"] = "on_pace"
            else:
                # info のみ (カフェイン): 多い/少ないを示すだけ
                item["status"] = "high" if pct > 1.4 else ("low" if pct < _BEHIND else "normal")
        habits.append(item)

    nudges = [h["nudge"] for h in habits if h["nudge"]]
    return {
        "now": now_jst.isoformat(timespec="minutes"),
        "habits": habits,
        "nudges": nudges,
    }

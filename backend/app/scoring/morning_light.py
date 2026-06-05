"""朝の屋外光暴露 proxy。

# 医学的根拠
朝の屋外光 (1000+ lux を 10-30 分) は:
- メラトニンを朝に強制終了 → circadian phase advance (Burns 2023 JAMA Psychiatry)
- 日中の覚醒度・気分・夜の睡眠の質を底上げ (Hattar lab 2019)
- 視床下部 SCN を介して PFC への投射経路を活性化、認知パフォーマンス向上

# Proxy の計算
直接的な lux センサーが無いため、以下を組み合わせて 0-100 スコア化:

1. **起床+0〜+3h の歩数**: 屋外活動量の代理 (Garmin metric_sample.steps_hourly)
   - 屋内のデスクワークでも歩数は出るが、200歩/h 未満なら屋外不在の可能性大
   - 1500歩/h 超は明確に屋外活動
2. **日中時間帯であるか**: 起床時刻が日の出後か (=自然光あり)
3. **天気 (晴れ vs 雨)**: 曇天でも屋外は 10,000 lux 出るので影響は小、ただし豪雨は減衰

シンプル実装: 起床+3h までの歩数合計から 0-100 にマップ。
- 0-500 歩: 0-30
- 500-3000 歩: 30-80
- 3000+ 歩: 80-100
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MetricSample


def compute_morning_light_score(
    session: Session,
    target: date,
    *,
    wake_hhmm: str = "06:30",
    window_hours: int = 3,
    tz_name: str = "Asia/Tokyo",
) -> dict[str, Any]:
    """起床+window_hours の屋外光暴露 proxy を算出する。

    優先順位:
    1. Apple Health (iOS 17+) の ``time_in_daylight`` (秒 or 分単位)
    2. 起床+window_hours の歩数合計から推定

    Returns:
        {
            "score": 0-100 or None,
            "steps_in_window": int,
            "daylight_min": int | None,  # 直接測定値があれば
            "source": "apple_daylight" | "steps_proxy" | None,
            "window_start_jst": "HH:MM",
            "window_end_jst": "HH:MM",
            "rationale": str,
        }
    """
    tz = ZoneInfo(tz_name)
    h, _, m = wake_hhmm.partition(":")
    wake_dt_jst = datetime.combine(target, datetime.min.time(), tz).replace(
        hour=int(h), minute=int(m)
    )
    window_end_jst = wake_dt_jst + timedelta(hours=window_hours)
    start_utc = wake_dt_jst.astimezone(UTC).replace(tzinfo=None)
    end_utc = window_end_jst.astimezone(UTC).replace(tzinfo=None)

    # --- 1. Apple Health の time_in_daylight (iOS 17+, Apple Watch 計測) ---
    # HAE の metric 名は通常スネークケース、単位は秒 (s) または分 (min) で送られる
    daylight_rows = session.execute(
        select(MetricSample.value, MetricSample.unit).where(
            MetricSample.ts >= start_utc,
            MetricSample.ts < end_utc,
            MetricSample.metric_key.in_(("time_in_daylight", "daylight_time")),
            MetricSample.value.is_not(None),
        )
    ).all()
    daylight_min: float | None = None
    if daylight_rows:
        total = 0.0
        for v, unit in daylight_rows:
            if v is None:
                continue
            val = float(v)
            # 秒単位なら 60 で割る (HAE のデフォルトは秒のことが多い)
            if unit and unit.lower() in ("s", "sec", "second", "seconds"):
                val = val / 60.0
            elif unit and unit.lower() in ("h", "hr", "hour", "hours"):
                val = val * 60.0
            total += val
        daylight_min = total

    # --- 2. 歩数 ---
    rows = session.execute(
        select(MetricSample.value).where(
            MetricSample.ts >= start_utc,
            MetricSample.ts < end_utc,
            MetricSample.metric_key.in_(("steps", "step_count")),
            MetricSample.value.is_not(None),
        )
    ).all()
    steps = sum(float(r[0]) for r in rows if r[0] is not None)

    source: str | None = None
    score: float | None = None
    rationale: str

    if daylight_min is not None and daylight_min > 0:
        score = _daylight_min_to_score(daylight_min)
        source = "apple_daylight"
        if score >= 80:
            rationale = (
                f"朝 {window_hours}h で日光下 {int(daylight_min)} 分 (Apple Watch 計測)、十分"
            )
        elif score >= 50:
            rationale = (
                f"朝 {window_hours}h で日光下 {int(daylight_min)} 分、もう少し屋外活動推奨"
            )
        else:
            rationale = (
                f"朝 {window_hours}h で日光下 {int(daylight_min)} 分、屋外光暴露不足"
            )
    elif steps > 0:
        score = _steps_to_score(steps)
        source = "steps_proxy"
        if score >= 80:
            rationale = f"朝 {window_hours}h で {int(steps)} 歩、十分な屋外暴露の可能性"
        elif score >= 50:
            rationale = (
                f"朝 {window_hours}h で {int(steps)} 歩、もう少し屋外活動を増やすと夜の睡眠が改善"
            )
        else:
            rationale = f"朝 {window_hours}h で {int(steps)} 歩、屋外光暴露不足の可能性"
    else:
        rationale = "起床+3h の活動データなし (屋外暴露不明)"

    return {
        "score": round(score, 1) if score is not None else None,
        "steps_in_window": int(steps),
        "daylight_min": int(daylight_min) if daylight_min is not None else None,
        "source": source,
        "window_start_jst": wake_dt_jst.strftime("%H:%M"),
        "window_end_jst": window_end_jst.strftime("%H:%M"),
        "rationale": rationale,
    }


def _daylight_min_to_score(minutes: float) -> float:
    """直接測定の日光暴露分 → 0-100 スコア。

    医学的目標: 朝の 1000+lux で 10-30 分が circadian phase advance に十分。
    - 5 分: 30
    - 15 分: 70
    - 30 分: 95
    - 60 分以上: 100
    """
    m = max(0.0, minutes)
    if m <= 0:
        return 0.0
    if m < 5:
        return m / 5 * 30.0
    if m < 15:
        return 30.0 + (m - 5) / 10 * 40.0
    if m < 30:
        return 70.0 + (m - 15) / 15 * 25.0
    if m < 60:
        return 95.0 + (m - 30) / 30 * 5.0
    return 100.0


def _steps_to_score(steps: float) -> float:
    """歩数 → 0-100 のスコア (上記コメントの 3 段階線形)。"""
    if steps <= 0:
        return 0.0
    if steps < 500:
        return steps / 500 * 30.0
    if steps < 3000:
        return 30.0 + (steps - 500) / 2500 * 50.0
    if steps < 6000:
        return 80.0 + (steps - 3000) / 3000 * 20.0
    return 100.0

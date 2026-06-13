"""人体マップ: 部位別の筋負荷 (回復) + 統合ステータス (Tarkov 風 HP ゲージ)。

2 つのビューを 1 つのデータで返す:
- muscle: 5 機能群 (肩/引く/脚/体幹/押す) を前/後の人体に回復色で乗せる。
  color 意味は既存カードと統一 — 緑=回復済み(やれる) / 橙→赤=直近に負荷(回復中)。
- hp: 体の部位に健康指標をマップしたゲージ (緑=良好 / 赤=要注意)。
  これは "HP" の literal ではなく UX メタファで、各ゲージは実指標の裏付けつき:
    頭=偏頭痛 / 胸=自律神経の回復(Body Battery) / 腹=水分 / 腕=上半身筋 / 脚=脚筋。

全て読み取り専用 (既存データを都度集計)。値が取れない指標は value=None で誠実に欠損表示。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.db import session_scope
from app.models import BodyBatteryDaily, MetricSample, MigraineEpisode
from app.scoring import bodyload

_HYDRATION_TARGET_ML = 2000.0  # EFSA 目安 (飲料由来)。これで 100%


def _clamp(v: float) -> int:
    return max(0, min(100, round(v)))


def _hp_gauges(
    now: datetime, groups: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], int | None]:
    today = (now + timedelta(hours=9)).date()  # JST 日付
    day_start = now - timedelta(hours=24)

    with session_scope() as session:
        # 頭: 直近14日の偏頭痛回数 → リスク (0回=100, 多いほど低い)
        mig_count = session.execute(
            select(func.count(MigraineEpisode.id)).where(
                MigraineEpisode.started_at >= now - timedelta(days=14)
            )
        ).scalar() or 0
        # 胸: 当日の Body Battery 朝値 (自律神経の回復度, 0-100)
        bb_morning = session.execute(
            select(BodyBatteryDaily.morning_value)
            .where(BodyBatteryDaily.date == today)
        ).scalar()
        # 腹: 当日の水分 (Garmin hydration ml 合計)
        water_ml = session.execute(
            select(func.sum(MetricSample.value)).where(
                MetricSample.metric_key == "garmin_hydration_ml",
                MetricSample.ts >= day_start,
                MetricSample.ts <= now,
            )
        ).scalar()

    head = _clamp(100 - min(100, mig_count * 25))  # 4回/14日で 0
    thorax = _clamp(float(bb_morning)) if bb_morning is not None else None
    stomach = _clamp(min(100.0, water_ml / _HYDRATION_TARGET_ML * 100)) if water_ml else None

    def _recov(keys: list[str]) -> int | None:
        vals = [groups[k]["recovery_pct"] for k in keys if groups[k]["confidence"] != "none"]
        return _clamp(sum(vals) / len(vals)) if vals else None

    arms = _recov(["push", "pull", "shoulders"])
    legs = _recov(["legs"])

    gauges = [
        {"region": "head", "label": "頭", "metric": "偏頭痛リスク", "value": head,
         "detail": f"直近14日 {mig_count}回" if mig_count else "直近14日 なし"},
        {"region": "thorax", "label": "胸", "metric": "自律神経の回復", "value": thorax,
         "detail": "Body Battery 朝値" if thorax is not None else "データなし"},
        {"region": "stomach", "label": "腹", "metric": "水分", "value": stomach,
         "detail": f"{round(water_ml)}/{round(_HYDRATION_TARGET_ML)}ml" if water_ml else "記録なし"},
        {"region": "arm", "label": "腕", "metric": "上半身の回復", "value": arms,
         "detail": "押す/引く/肩の平均" if arms is not None else "刺激記録なし"},
        {"region": "leg", "label": "脚", "metric": "脚の回復", "value": legs,
         "detail": "脚の回復%" if legs is not None else "刺激記録なし"},
    ]
    vals = [g["value"] for g in gauges if g["value"] is not None]
    total = round(sum(vals) / len(vals)) if vals else None
    return gauges, total


def state(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    bl = bodyload.state(now=now)
    groups = {g["key"]: g for g in bl["groups"]}
    suggested = {x["key"] for x in bl["suggestion"]}

    # 筋負荷マップ: bodyload の群をそのまま (回復色は recovery_pct, おすすめは suggested)
    muscle = [
        {
            "key": g["key"], "label": g["label"], "recovery_pct": g["recovery_pct"],
            "confidence": g["confidence"], "suggested": g["key"] in suggested,
            "week_load": g["week_load"], "home": g["home"], "hours_since": g["hours_since"],
        }
        for g in bl["groups"]
    ]

    gauges, total = _hp_gauges(now, groups)
    return {
        "muscle": muscle,
        "suggestion": bl["suggestion"],
        "muscle_confidence": bl["confidence"],
        "hp": gauges,
        "hp_total": total,
    }

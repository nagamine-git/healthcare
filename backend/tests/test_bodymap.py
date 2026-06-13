from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import BodyBatteryDaily, MetricSample, MigraineEpisode, Workout
from app.scoring import bodymap


def test_empty_state_shape(db_engine):
    now = datetime(2026, 6, 13, 0, 0)
    s = bodymap.state(now=now)
    assert len(s["muscle"]) == 5
    regions = {g["region"] for g in s["hp"]}
    assert regions == {"head", "thorax", "stomach", "arm", "leg"}
    # 偏頭痛なし → 頭は満タン。他はデータなし → None
    head = next(g for g in s["hp"] if g["region"] == "head")
    assert head["value"] == 100
    thorax = next(g for g in s["hp"] if g["region"] == "thorax")
    assert thorax["value"] is None


def test_hp_gauges_from_real_metrics(db_engine):
    now = datetime(2026, 6, 13, 0, 0)
    today = (now + timedelta(hours=9)).date()
    with session_scope() as ss:
        ss.add(BodyBatteryDaily(date=today, morning_value=72))
        ss.add(MetricSample(source="garmin", metric_key="garmin_hydration_ml",
                            ts=now - timedelta(hours=3), value=1000.0))
        ss.add(MigraineEpisode(started_at=now - timedelta(days=2)))
        ss.add(Workout(id="w1", source="garmin", start=now - timedelta(days=4),
                       type="boxing", duration_s=1800, training_load=60))
    s = bodymap.state(now=now)
    hp = {g["region"]: g for g in s["hp"]}
    assert hp["thorax"]["value"] == 72  # Body Battery
    assert hp["stomach"]["value"] == 50  # 1000/2000ml
    assert hp["head"]["value"] == 75  # 1回 → 100-25
    assert s["hp_total"] is not None
    # boxing で肩が刺激 → 筋負荷マップに反映
    sh = next(m for m in s["muscle"] if m["key"] == "shoulders")
    assert sh["confidence"] == "inferred"

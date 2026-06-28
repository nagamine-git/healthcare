from __future__ import annotations

from datetime import UTC

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.ingest.hae_parser import (
    NormalizedSample,
    NormalizedSleep,
    NormalizedWeight,
    NormalizedWorkout,
    ParseResult,
)
from app.models import (
    MetricSample,
    SleepSession,
    SourceSync,
    WeightSample,
    Workout,
)


def write_parse_result(session: Session, result: ParseResult) -> dict[str, int]:
    counts = {
        "samples": _write_samples(session, result.samples),
        "weights": _write_weights(session, result.weights),
        "sleeps": _write_sleeps(session, result.sleeps),
        "workouts": _write_workouts(session, result.workouts),
    }
    _bump_source_sync(session, "hae")
    session.commit()
    return counts


# SQLite の 1 ステートメントあたりパラメータ数上限は 32766。
# metric_sample は 6 列なので 5000 行で 30000 パラメータ → 安全。
_BATCH_ROWS = 500


def _write_samples(session: Session, samples: list[NormalizedSample]) -> int:
    if not samples:
        return 0
    payload = [
        {
            "source": s.source,
            "metric_key": s.metric_key,
            "ts": s.ts.replace(tzinfo=None),
            "value": s.value,
            "unit": s.unit,
            "raw_json": s.raw,
        }
        for s in samples
    ]
    for chunk_start in range(0, len(payload), _BATCH_ROWS):
        chunk = payload[chunk_start : chunk_start + _BATCH_ROWS]
        stmt = sqlite_insert(MetricSample).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[MetricSample.source, MetricSample.metric_key, MetricSample.ts],
            set_={
                "value": stmt.excluded.value,
                "unit": stmt.excluded.unit,
                "raw_json": stmt.excluded.raw_json,
            },
        )
        session.execute(stmt)
    return len(samples)


def _write_weights(session: Session, weights: list[NormalizedWeight]) -> int:
    if not weights:
        return 0
    payload = [
        {
            "ts": w.ts.replace(tzinfo=None),
            "weight_kg": w.weight_kg,
            "body_fat_pct": w.body_fat_pct,
            "muscle_kg": w.muscle_kg,
            "water_pct": w.water_pct,
            "source": w.source,
        }
        for w in weights
    ]
    for chunk_start in range(0, len(payload), _BATCH_ROWS):
        chunk = payload[chunk_start : chunk_start + _BATCH_ROWS]
        stmt = sqlite_insert(WeightSample).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[WeightSample.ts],
            set_={
                "weight_kg": stmt.excluded.weight_kg,
                "body_fat_pct": stmt.excluded.body_fat_pct,
                "muscle_kg": stmt.excluded.muscle_kg,
                "water_pct": stmt.excluded.water_pct,
                "source": stmt.excluded.source,
            },
        )
        session.execute(stmt)
    return len(weights)


def _write_sleeps(session: Session, sleeps: list[NormalizedSleep]) -> int:
    if not sleeps:
        return 0
    written = 0
    for sleep in sleeps:
        existing = session.get(SleepSession, sleep.date)
        # Garmin wins over HAE if both present.
        if existing and existing.source == "garmin":
            continue
        if existing:
            existing.source = sleep.source
            existing.total_min = sleep.total_min
            existing.deep_min = sleep.deep_min
            existing.rem_min = sleep.rem_min
            existing.light_min = sleep.light_min
            existing.awake_min = sleep.awake_min
            existing.sleep_score = sleep.sleep_score
            existing.raw_json = sleep.raw_json
        else:
            session.add(
                SleepSession(
                    date=sleep.date,
                    source=sleep.source,
                    total_min=sleep.total_min,
                    deep_min=sleep.deep_min,
                    rem_min=sleep.rem_min,
                    light_min=sleep.light_min,
                    awake_min=sleep.awake_min,
                    sleep_score=sleep.sleep_score,
                    raw_json=sleep.raw_json,
                )
            )
        written += 1
    return written


def _write_workouts(session: Session, workouts: list[NormalizedWorkout]) -> int:
    if not workouts:
        return 0
    written = 0
    for w in workouts:
        existing = session.get(Workout, w.id)
        if existing:
            existing.start = w.start.replace(tzinfo=None)
            existing.end = w.end.replace(tzinfo=None) if w.end else None
            existing.type = w.type
            existing.duration_s = w.duration_s
            existing.distance_m = w.distance_m
            existing.kcal = w.kcal
            existing.avg_hr = w.avg_hr
            existing.max_hr = w.max_hr
            existing.raw_json = w.raw_json
        else:
            session.add(
                Workout(
                    id=w.id,
                    source=w.source,
                    start=w.start.replace(tzinfo=None),
                    end=w.end.replace(tzinfo=None) if w.end else None,
                    type=w.type,
                    duration_s=w.duration_s,
                    distance_m=w.distance_m,
                    kcal=w.kcal,
                    avg_hr=w.avg_hr,
                    max_hr=w.max_hr,
                    raw_json=w.raw_json,
                )
            )
        written += 1
    return written


def _bump_source_sync(session: Session, source: str) -> None:
    from datetime import datetime

    now = datetime.now(UTC).replace(tzinfo=None)
    existing = session.get(SourceSync, source)
    if existing:
        existing.last_synced_at = now
        existing.last_error = None
    else:
        session.add(SourceSync(source=source, last_synced_at=now))


"""Garmin sync orchestration. The actual client is in :mod:`app.ingest.garmin_client`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.ingest.garmin_client import GarminClient
from app.logging import get_logger
from app.models import (
    BodyBattery,
    BodyBatteryDaily,
    DailySummary,
    HrvDaily,
    MetricSample,
    SleepSession,
    SourceSync,
    Workout,
)

logger = get_logger(__name__)


def sync_garmin(client: GarminClient, target: date_type | None = None) -> dict[str, Any]:
    target = target or datetime.now().date()
    counts = {
        "sleep": 0,
        "hrv": 0,
        "body_battery": 0,
        "workouts": 0,
        "summary": 0,
        "weight": 0,
        "stress": 0,
    }
    error: str | None = None

    try:
        # Sleep
        sleep = client.get_sleep(target)
        if sleep:
            with session_scope() as session:
                _upsert_sleep(session, target, sleep)
            counts["sleep"] = 1

        hrv = client.get_hrv(target)
        if hrv:
            with session_scope() as session:
                _upsert_hrv(session, target, hrv)
            counts["hrv"] = 1

        bb = client.get_body_battery(target)
        if bb:
            with session_scope() as session:
                counts["body_battery"] = _upsert_body_battery(session, target, bb)

        workouts = client.get_workouts(target)
        if workouts:
            with session_scope() as session:
                counts["workouts"] = _upsert_workouts(session, workouts)

        summary = client.get_user_summary(target)
        if summary:
            with session_scope() as session:
                _upsert_summary(session, target, summary)
            counts["summary"] = 1

        stress = client.get_stress(target)
        if stress:
            with session_scope() as session:
                counts["stress"] = _upsert_stress(session, stress)

        hydration = client.get_hydration(target)
        if hydration:
            with session_scope() as session:
                counts["hydration"] = _upsert_hydration(session, hydration)

        readiness = client.get_training_readiness(target)
        if readiness:
            with session_scope() as session:
                _upsert_daily_metric(
                    session, target, "training_readiness",
                    readiness["score"], "score", readiness.get("factors"),
                )
            counts["readiness"] = 1

        fitness_age = client.get_fitness_age(target)
        if fitness_age:
            with session_scope() as session:
                _upsert_daily_metric(
                    session, target, "fitness_age",
                    fitness_age["fitness_age"], "歳", fitness_age.get("raw"),
                )
            counts["fitness_age"] = 1

        respiration = client.get_respiration(target)
        if respiration:
            with session_scope() as session:
                _upsert_daily_metric(
                    session, target, "respiration_waking_avg",
                    respiration["waking_avg"], "brpm", None,
                )
            counts["respiration"] = 1

        floors = client.get_floors(target)
        if floors:
            with session_scope() as session:
                _upsert_daily_metric(
                    session, target, "floors_up", floors["ascended"], "階", None,
                )
            counts["floors"] = 1

    except Exception as exc:
        error = str(exc)
        logger.warning("garmin_sync_error", error=error)

    with session_scope() as session:
        _record_sync(session, "garmin", error)

    return {"counts": counts, "error": error}


def _has_garmin_token(settings: Any) -> bool:
    """Garmin OAuth トークンが既にキャッシュされているか確認する。

    トークンが無い状態で sync を回すと credential login → Garmin の
    IP rate limit (HTTP 429) を踏むため、初回は対話ログイン
    (``python -m app.cli garmin-login``) を強制する。

    python-garminconnect は 0.3 系で ``garmin_tokens.json`` 単一ファイルに
    まとめる仕様 (旧バージョンは oauth1_token.json / oauth2_token.json)。
    どちらの形式も検出する。
    """
    token_dir = settings.resolved_garmin_token_dir()
    if not token_dir.exists():
        return False
    for name in ("garmin_tokens.json", "oauth1_token.json", "oauth2_token.json"):
        if (token_dir / name).exists():
            return True
    return False


async def sync_garmin_job() -> dict[str, Any]:
    settings = get_settings()
    if not (settings.garmin_email and settings.garmin_password):
        logger.info("garmin_sync_skipped_no_credentials")
        return {"status": "skipped", "reason": "no_credentials"}

    if not _has_garmin_token(settings):
        logger.info(
            "garmin_sync_skipped_no_token",
            token_dir=str(settings.resolved_garmin_token_dir()),
            hint="run `python -m app.cli garmin-login` once to seed the token",
        )
        return {"status": "skipped", "reason": "no_token"}

    client = GarminClient.from_settings(settings)
    return sync_garmin(client)


def _upsert_sleep(session: Session, target: date_type, sleep: dict[str, Any]) -> None:
    from app.ingest.sleep_extras import store_sleep_extras

    existing = session.get(SleepSession, target)
    fields = {
        "source": "garmin",
        "total_min": sleep.get("total_min"),
        "deep_min": sleep.get("deep_min"),
        "rem_min": sleep.get("rem_min"),
        "light_min": sleep.get("light_min"),
        "awake_min": sleep.get("awake_min"),
        "sleep_score": sleep.get("sleep_score"),
        "hrv_overnight_avg": sleep.get("hrv_overnight_avg"),
        "raw_json": sleep.get("raw_json"),
    }
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(SleepSession(date=target, **fields))

    # raw_json から生理指標 (SpO2/呼吸/睡眠中点 等) を MetricSample へ抽出
    store_sleep_extras(session, target, sleep.get("raw_json"))


def _upsert_hrv(session: Session, target: date_type, hrv: dict[str, Any]) -> None:
    existing = session.get(HrvDaily, target)
    fields = {
        "last_night_avg": hrv.get("last_night_avg"),
        "weekly_avg": hrv.get("weekly_avg"),
        "status": hrv.get("status"),
        "baseline_low": hrv.get("baseline_low"),
        "baseline_high": hrv.get("baseline_high"),
    }
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(HrvDaily(date=target, **fields))


def _upsert_body_battery(session: Session, target: date_type, bb: dict[str, Any]) -> int:
    series: list[dict[str, Any]] = bb.get("series") or []
    written = 0
    for point in series:
        ts = point.get("ts")
        value = point.get("value")
        if not isinstance(ts, datetime) or value is None:
            continue
        ts_naive = ts.astimezone(UTC).replace(tzinfo=None) if ts.tzinfo else ts
        existing = session.get(BodyBattery, ts_naive)
        if existing:
            existing.value = value
        else:
            session.add(BodyBattery(ts=ts_naive, value=value))
        written += 1

    if "morning" in bb:
        existing_daily = session.get(BodyBatteryDaily, target)
        fields = {
            "max_value": bb.get("max"),
            "min_value": bb.get("min"),
            "end_of_day": bb.get("end_of_day"),
            "morning_value": bb.get("morning"),
        }
        if existing_daily:
            for k, v in fields.items():
                setattr(existing_daily, k, v)
        else:
            session.add(BodyBatteryDaily(date=target, **fields))
    return written


def _upsert_workouts(session: Session, workouts: list[dict[str, Any]]) -> int:
    n = 0
    for w in workouts:
        wid = f"garmin-{w.get('id')}"
        start = w.get("start")
        if not isinstance(start, datetime):
            continue
        start_naive = start.replace(tzinfo=None) if start.tzinfo else start
        end_naive = (
            w["end"].replace(tzinfo=None) if isinstance(w.get("end"), datetime) and w["end"].tzinfo else w.get("end")
        )

        existing = session.get(Workout, wid)
        fields = {
            "source": "garmin",
            "start": start_naive,
            "end": end_naive,
            "type": w.get("type"),
            "duration_s": w.get("duration_s"),
            "distance_m": w.get("distance_m"),
            "kcal": w.get("kcal"),
            "training_load": w.get("training_load"),
            "avg_hr": w.get("avg_hr"),
            "max_hr": w.get("max_hr"),
            "raw_json": w.get("raw_json"),
        }
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            session.add(Workout(id=wid, **fields))
        n += 1
    return n


def _upsert_summary(session: Session, target: date_type, summary: dict[str, Any]) -> None:
    existing = session.get(DailySummary, target)
    fields = {
        "steps": summary.get("steps"),
        "active_kcal": summary.get("active_kcal"),
        "resting_hr": summary.get("resting_hr"),
        "vo2max": summary.get("vo2max"),
        "training_status": summary.get("training_status"),
    }
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(DailySummary(date=target, **fields))

    # 朝光暴露 proxy の補助として intensity minutes を metric_sample に保存
    for key, val in (
        ("intensity_minutes_moderate", summary.get("moderate_intensity_min")),
        ("intensity_minutes_vigorous", summary.get("vigorous_intensity_min")),
    ):
        if val is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        # date 単位なので JST 朝に統一 (7:00) して 1 サンプル
        ts = datetime.combine(target, datetime.min.time()).replace(hour=7)
        stmt = sqlite_insert(MetricSample).values(
            [
                {
                    "source": "garmin",
                    "metric_key": key,
                    "ts": ts,
                    "value": v,
                    "unit": "min",
                    "raw_json": None,
                }
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                MetricSample.source,
                MetricSample.metric_key,
                MetricSample.ts,
            ],
            set_={"value": stmt.excluded.value},
        )
        session.execute(stmt)


def _upsert_daily_metric(
    session: Session,
    target: date_type,
    key: str,
    value: float,
    unit: str | None,
    raw_json: dict[str, Any] | None,
) -> None:
    """日次 1 サンプルの指標を MetricSample に upsert (ts=対象日 07:00)。"""
    ts = datetime.combine(target, datetime.min.time()).replace(hour=7)
    stmt = sqlite_insert(MetricSample).values(
        [{
            "source": "garmin",
            "metric_key": key,
            "ts": ts,
            "value": float(value),
            "unit": unit,
            "raw_json": raw_json,
        }]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[MetricSample.source, MetricSample.metric_key, MetricSample.ts],
        set_={"value": stmt.excluded.value, "raw_json": stmt.excluded.raw_json},
    )
    session.execute(stmt)


def _upsert_hydration(session: Session, hydration: dict[str, Any]) -> int:
    """Garmin Hydration を MetricSample に書く (key=garmin_hydration_ml)。"""
    ts = hydration.get("ts")
    value = hydration.get("value_ml")
    if not isinstance(ts, datetime) or value is None:
        return 0
    ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
    raw = hydration.get("raw_json") or {}
    # raw_json の datetime は JSON serialize できないので除外
    safe_raw = {k: v for k, v in raw.items() if not isinstance(v, datetime)}
    payload = [
        {
            "source": "garmin",
            "metric_key": "garmin_hydration_ml",
            "ts": ts_naive,
            "value": float(value),
            "unit": "mL",
            "raw_json": safe_raw,
        }
    ]
    stmt = sqlite_insert(MetricSample).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[MetricSample.source, MetricSample.metric_key, MetricSample.ts],
        set_={"value": stmt.excluded.value, "raw_json": stmt.excluded.raw_json},
    )
    session.execute(stmt)
    return 1


def _upsert_stress(session: Session, stress: list[dict[str, Any]]) -> int:
    if not stress:
        return 0
    payload = []
    for point in stress:
        ts = point.get("ts")
        value = point.get("value")
        if not isinstance(ts, datetime):
            continue
        ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
        payload.append(
            {
                "source": "garmin",
                "metric_key": "stress",
                "ts": ts_naive,
                "value": value,
                "unit": "level",
                "raw_json": {"ts": ts.isoformat(), "value": value},
            }
        )
    if not payload:
        return 0
    stmt = sqlite_insert(MetricSample).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[MetricSample.source, MetricSample.metric_key, MetricSample.ts],
        set_={"value": stmt.excluded.value, "raw_json": stmt.excluded.raw_json},
    )
    session.execute(stmt)
    return len(payload)


def _record_sync(session: Session, source: str, error: str | None) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    existing = session.get(SourceSync, source)
    if existing:
        existing.last_synced_at = now
        existing.last_error = error
    else:
        session.add(SourceSync(source=source, last_synced_at=now, last_error=error))


def _yesterday() -> date_type:
    return datetime.now().date() - timedelta(days=1)

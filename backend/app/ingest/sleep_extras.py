"""sleep_session.raw_json から生理指標を抽出して MetricSample に書く。

Garmin の睡眠レスポンスには SpO2・呼吸数・睡眠中ストレス・夜間安静時心拍・
寝返り・Body Battery 回復量・昼寝・就寝/起床時刻 (→睡眠中点) が含まれるが、
従来は total_min 等の基本値しか使っていなかった。ここで全て抽出する。

スキーマ変更を避けるため metric_sample (source="garmin", ts=対象日 07:00) に
upsert する。sync 時に毎回呼ばれるほか、過去分は backfill_sleep_extras() で
一括処理できる。
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import MetricSample, SleepSession

# breathingDisruptionSeverity の数値化
_BREATH_DISRUPTION = {"LOW": 0.0, "MODERATE": 1.0, "HIGH": 2.0}


def _local_hour(epoch_ms: Any) -> float | None:
    """Garmin の *TimestampLocal (ローカル壁時計の epoch ms) を時 (小数) に変換。"""
    if not isinstance(epoch_ms, (int, float)):
        return None
    dt = datetime.fromtimestamp(float(epoch_ms) / 1000.0, tz=UTC)
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def extract_sleep_extras(raw: dict[str, Any]) -> dict[str, float]:
    """raw_json から metric_key -> value の dict を返す。欠損はスキップ。"""
    dto = raw.get("dailySleepDTO") or {}
    out: dict[str, float] = {}

    direct = {
        "sleep_spo2_avg": dto.get("averageSpO2Value"),
        "sleep_spo2_lowest": dto.get("lowestSpO2Value"),
        "sleep_respiration_avg": dto.get("averageRespirationValue"),
        "sleep_stress_avg": dto.get("avgSleepStress"),
        "sleep_resting_hr": raw.get("restingHeartRate"),
        "sleep_restless_moments": raw.get("restlessMomentsCount"),
        "sleep_bb_change": raw.get("bodyBatteryChange"),
    }
    for key, val in direct.items():
        if val is None:
            continue
        try:
            out[key] = float(val)
        except (TypeError, ValueError):
            continue

    nap_s = dto.get("napTimeSeconds")
    if nap_s is not None:
        try:
            out["sleep_nap_min"] = float(nap_s) / 60.0
        except (TypeError, ValueError):
            pass

    severity = dto.get("breathingDisruptionSeverity")
    if isinstance(severity, str) and severity in _BREATH_DISRUPTION:
        out["sleep_breath_disruption"] = _BREATH_DISRUPTION[severity]

    # 睡眠中点 (概日リズムの標準指標)。start/end のローカル壁時計から計算。
    start_ms = dto.get("sleepStartTimestampLocal")
    end_ms = dto.get("sleepEndTimestampLocal")
    if isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float)) and end_ms > start_ms:
        mid_ms = (float(start_ms) + float(end_ms)) / 2.0
        mid_hour = _local_hour(mid_ms)
        if mid_hour is not None:
            out["sleep_midpoint_hour"] = round(mid_hour, 2)

    return out


def store_sleep_extras(session: Session, target: date_type, raw: dict[str, Any] | None) -> int:
    """抽出した指標を MetricSample に upsert。書いた行数を返す。"""
    if not raw:
        return 0
    metrics = extract_sleep_extras(raw)
    if not metrics:
        return 0
    ts = datetime.combine(target, datetime.min.time()).replace(hour=7)
    payload = [
        {
            "source": "garmin",
            "metric_key": key,
            "ts": ts,
            "value": round(value, 2),
            "unit": None,
            "raw_json": None,
        }
        for key, value in metrics.items()
    ]
    stmt = sqlite_insert(MetricSample).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[MetricSample.source, MetricSample.metric_key, MetricSample.ts],
        set_={"value": stmt.excluded.value},
    )
    session.execute(stmt)
    return len(payload)


def backfill_sleep_extras() -> int:
    """既存の sleep_session.raw_json 全件から抽出。処理した日数を返す。"""
    processed = 0
    with session_scope() as session:
        rows = session.execute(
            select(SleepSession.date, SleepSession.raw_json).where(
                SleepSession.raw_json.is_not(None))
        ).all()
        for target, raw in rows:
            if store_sleep_extras(session, target, raw) > 0:
                processed += 1
    return processed

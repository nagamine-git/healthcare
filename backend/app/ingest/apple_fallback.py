"""Garmin 欠測の夜を Apple Watch(HAE)由来データで補完する。

方針(医学的正しさを優先):
- **SpO2** は機器間で比較可能な絶対値なので、Garmin が欠測の夜に限り Apple の
  ``blood_oxygen_saturation`` から ``sleep_spo2_avg`` / ``sleep_spo2_lowest`` を生成し、
  既存の睡眠時 SpO2 低下アラートにそのまま供給する(source="hae")。
- **HRV** は Apple=SDNN / Garmin=RMSSD で**別指標**。混ぜると RMSSD ベースラインと
  z 値が汚染されるため、``HrvDaily.last_night_avg`` には決して入れない。別キー
  ``sleep_hrv_sdnn_hae`` に「参照値」として保存するだけに留める(スコア非関与)。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MetricSample

_UTC = ZoneInfo("UTC")
# Apple の参照用 HRV(SDNN)を書くキー。Garmin RMSSD の hrv_daily とは別物。
APPLE_HRV_KEY = "sleep_hrv_sdnn_hae"


def _overnight_utc_window(target: date_type) -> tuple[datetime, datetime]:
    """target の「昨夜」に相当する UTC 素朴時刻の窓 [D-1 20:00, D 11:00)(app_tz ローカル)。"""
    tz = ZoneInfo(get_settings().app_tz)
    lo = datetime.combine(target - timedelta(days=1), time(20, 0), tzinfo=tz)
    hi = datetime.combine(target, time(11, 0), tzinfo=tz)
    return (
        lo.astimezone(_UTC).replace(tzinfo=None),
        hi.astimezone(_UTC).replace(tzinfo=None),
    )


def _apple_values(session: Session, key: str, lo: datetime, hi: datetime) -> list[float]:
    rows = session.execute(
        select(MetricSample.value).where(
            MetricSample.source == "hae",
            MetricSample.metric_key == key,
            MetricSample.ts >= lo,
            MetricSample.ts < hi,
        )
    ).all()
    return [float(r[0]) for r in rows if r[0] is not None]


def _garmin_has(session: Session, key: str, ts: datetime) -> bool:
    return (
        session.execute(
            select(MetricSample.id).where(
                MetricSample.source == "garmin",
                MetricSample.metric_key == key,
                MetricSample.ts == ts,
            )
        ).first()
        is not None
    )


def _upsert_hae(session: Session, key: str, ts: datetime, value: float) -> None:
    stmt = sqlite_insert(MetricSample).values(
        source="hae", metric_key=key, ts=ts, value=round(value, 1), unit=None, raw_json=None
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[MetricSample.source, MetricSample.metric_key, MetricSample.ts],
        set_={"value": stmt.excluded.value},
    )
    session.execute(stmt)


def _delete_hae(session: Session, keys: list[str], ts: datetime) -> None:
    session.execute(
        delete(MetricSample).where(
            MetricSample.source == "hae",
            MetricSample.metric_key.in_(keys),
            MetricSample.ts == ts,
        )
    )


def apply_apple_sleep_fallback(session: Session, target: date_type) -> dict[str, float | int]:
    """target の夜について Apple 由来の補完を材料化する。書いた内容の要約を返す。"""
    lo, hi = _overnight_utc_window(target)
    ts = datetime.combine(target, time(7, 0))  # store_sleep_extras と同じ夜次マーカー
    out: dict[str, float | int] = {}

    # --- SpO2: Garmin 欠測時のみ Apple で補完(あればフォールバックは撤去=self-heal)---
    if _garmin_has(session, "sleep_spo2_avg", ts):
        _delete_hae(session, ["sleep_spo2_avg", "sleep_spo2_lowest"], ts)
    else:
        spo2 = _apple_values(session, "blood_oxygen_saturation", lo, hi)
        if spo2:
            _upsert_hae(session, "sleep_spo2_avg", ts, mean(spo2))
            _upsert_hae(session, "sleep_spo2_lowest", ts, min(spo2))
            out["spo2_n"] = len(spo2)
            out["spo2_avg"] = round(mean(spo2), 1)
            out["spo2_lowest"] = round(min(spo2), 1)

    # --- HRV: 参照値として別キーに保存(スコア/ベースライン非関与)---
    hrv = _apple_values(session, "heart_rate_variability", lo, hi)
    if hrv:
        _upsert_hae(session, APPLE_HRV_KEY, ts, mean(hrv))
        out["hrv_sdnn"] = round(mean(hrv), 1)
        out["hrv_n"] = len(hrv)

    return out

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)


class GarminAPIProtocol(Protocol):
    """Subset of the python-garminconnect API we depend on."""

    def login(self, tokenstore: str | None = ..., tokenstore_base64: str | None = ...) -> Any: ...
    def get_sleep_data(self, cdate: str) -> Any: ...
    def get_hrv_data(self, cdate: str) -> Any: ...
    def get_body_battery(self, startdate: str, enddate: str | None = ...) -> Any: ...
    def get_activities_by_date(self, startdate: str, enddate: str) -> Any: ...
    def get_user_summary(self, cdate: str) -> Any: ...
    def get_stress_data(self, cdate: str) -> Any: ...
    def get_hydration_data(self, cdate: str) -> Any: ...
    def get_training_readiness(self, cdate: str) -> Any: ...
    def get_fitnessage_data(self, cdate: str) -> Any: ...
    def get_respiration_data(self, cdate: str) -> Any: ...
    def get_floors(self, cdate: str) -> Any: ...
    def garth(self) -> Any: ...


class GarminClient:
    """Thin wrapper around python-garminconnect, with normalisation."""

    def __init__(self, api: GarminAPIProtocol, *, token_dir: Path | None = None) -> None:
        self._api = api
        self._token_dir = token_dir
        self._logged_in = False

    @classmethod
    def from_settings(cls, settings: Settings) -> GarminClient:
        from garminconnect import Garmin

        token_dir = settings.resolved_garmin_token_dir()
        token_dir.mkdir(parents=True, exist_ok=True)

        api = Garmin(email=settings.garmin_email, password=settings.garmin_password)
        return cls(api, token_dir=token_dir)

    def login(self) -> None:
        if self._logged_in:
            return
        try:
            self._api.login(tokenstore=str(self._token_dir) if self._token_dir else None)
            self._logged_in = True
        except Exception as exc:
            logger.warning("garmin_login_failed", error=str(exc))
            raise

    def get_sleep(self, target: date_type) -> dict[str, Any] | None:
        self.login()
        raw = self._api.get_sleep_data(target.isoformat())
        if not raw:
            return None
        return _normalise_sleep(raw)

    def get_hrv(self, target: date_type) -> dict[str, Any] | None:
        self.login()
        try:
            raw = self._api.get_hrv_data(target.isoformat())
        except Exception:
            return None
        if not raw:
            return None
        return _normalise_hrv(raw)

    def get_body_battery(self, target: date_type) -> dict[str, Any] | None:
        self.login()
        try:
            raw = self._api.get_body_battery(target.isoformat())
        except Exception:
            return None
        if not raw:
            return None
        return _normalise_body_battery(raw)

    def get_workouts(self, target: date_type) -> list[dict[str, Any]]:
        self.login()
        try:
            raw = self._api.get_activities_by_date(target.isoformat(), target.isoformat())
        except Exception:
            return []
        if not raw:
            return []
        return [_normalise_workout(a) for a in raw]

    def get_user_summary(self, target: date_type) -> dict[str, Any] | None:
        self.login()
        try:
            raw = self._api.get_user_summary(target.isoformat())
        except Exception:
            return None
        if not raw:
            return None
        return _normalise_summary(raw)

    def get_stress(self, target: date_type) -> list[dict[str, Any]]:
        self.login()
        try:
            raw = self._api.get_stress_data(target.isoformat())
        except Exception:
            return []
        return _normalise_stress(raw)

    def get_training_readiness(self, target: date_type) -> dict[str, Any] | None:
        """Training Readiness (0-100 合成スコア + 要因分解)。対応端末のみ値が返る。"""
        self.login()
        try:
            raw = self._api.get_training_readiness(target.isoformat())
        except Exception:
            return None
        return _normalise_training_readiness(raw)

    def get_fitness_age(self, target: date_type) -> dict[str, Any] | None:
        self.login()
        try:
            raw = self._api.get_fitnessage_data(target.isoformat())
        except Exception:
            return None
        return _normalise_fitness_age(raw)

    def get_respiration(self, target: date_type) -> dict[str, Any] | None:
        """日次呼吸サマリ (覚醒時平均)。睡眠時平均は sleep raw_json 側で取る。"""
        self.login()
        try:
            raw = self._api.get_respiration_data(target.isoformat())
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        v = raw.get("avgWakingRespirationValue")
        return {"waking_avg": float(v)} if v is not None else None

    def get_floors(self, target: date_type) -> dict[str, Any] | None:
        """当日の昇り階数合計。"""
        self.login()
        try:
            raw = self._api.get_floors(target.isoformat())
        except Exception:
            return None
        return _normalise_floors(raw)

    def get_hydration(self, target: date_type) -> dict[str, Any] | None:
        """Garmin Connect で記録された水分量 (日次集計、mL)。

        Garmin Connect アプリで「Hydration」ウィジェットを使って水分を記録している場合のみ
        値が返る。返り値: ``{"value_ml": N, "goal_ml": N, "ts": datetime}`` または None。
        """
        self.login()
        try:
            raw = self._api.get_hydration_data(target.isoformat())
        except Exception:
            return None
        return _normalise_hydration(raw, target)


# ---- normalisers ---------------------------------------------------------


def _to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Assume epoch ms
        return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
    try:
        from dateutil import parser as date_parser

        return date_parser.parse(str(value))
    except Exception:
        return None


def _normalise_sleep(raw: dict[str, Any]) -> dict[str, Any]:
    dto = raw.get("dailySleepDTO") or raw
    sleep_score = None
    if isinstance(dto.get("sleepScores"), dict):
        overall = dto["sleepScores"].get("overall") or {}
        sleep_score = overall.get("value")

    def secs(key: str) -> int | None:
        v = dto.get(key)
        return int(v / 60) if v is not None else None

    hrv_overnight_avg = None
    if isinstance(raw.get("hrvSummary"), dict):
        hrv_overnight_avg = raw["hrvSummary"].get("lastNightAvg")

    return {
        "total_min": secs("sleepTimeSeconds"),
        "deep_min": secs("deepSleepSeconds"),
        "rem_min": secs("remSleepSeconds"),
        "light_min": secs("lightSleepSeconds"),
        "awake_min": secs("awakeSleepSeconds"),
        "sleep_score": sleep_score,
        "hrv_overnight_avg": hrv_overnight_avg,
        "raw_json": raw,
    }


def _normalise_hrv(raw: dict[str, Any]) -> dict[str, Any]:
    summary = raw.get("hrvSummary") or raw
    baseline = summary.get("baseline") or {}
    return {
        "last_night_avg": summary.get("lastNightAvg"),
        "weekly_avg": summary.get("weeklyAvg"),
        "status": summary.get("status"),
        "baseline_low": baseline.get("lowUpper"),
        "baseline_high": baseline.get("balancedHigh"),
    }


def _normalise_body_battery(raw: list | dict) -> dict[str, Any]:
    """The Garmin response is typically a list with a single day envelope."""
    envelope: dict[str, Any]
    if isinstance(raw, list):
        if not raw:
            return {}
        envelope = raw[0]
    else:
        envelope = raw

    values_array: list[list[Any]] = envelope.get("bodyBatteryValuesArray") or []
    series: list[dict[str, Any]] = []
    for entry in values_array:
        if len(entry) < 2:
            continue
        ts = _to_dt(entry[0])
        if ts is None:
            continue
        # Some Garmin payloads embed "type, value" in the second/third positions.
        value = entry[2] if len(entry) >= 3 else entry[1]
        if value is None:
            continue
        try:
            series.append({"ts": ts, "value": float(value)})
        except (TypeError, ValueError):
            continue

    morning = None
    for point in series:
        local = point["ts"].astimezone() if point["ts"].tzinfo else point["ts"]
        if local.hour == 6:
            morning = point["value"]
            break

    if not morning and series:
        morning = series[0]["value"]

    values = [p["value"] for p in series]
    return {
        "series": series,
        "max": max(values) if values else None,
        "min": min(values) if values else None,
        "morning": morning,
        "end_of_day": series[-1]["value"] if series else None,
    }


def _normalise_workout(activity: dict[str, Any]) -> dict[str, Any]:
    start = _to_dt(activity.get("startTimeGMT") or activity.get("startTimeLocal"))
    end = None
    duration = activity.get("duration")
    if start and duration:
        from datetime import timedelta

        end = start + timedelta(seconds=int(duration))
    return {
        "id": activity.get("activityId"),
        "start": start,
        "end": end,
        "type": (activity.get("activityType") or {}).get("typeKey"),
        "duration_s": int(duration) if duration is not None else None,
        "distance_m": float(activity.get("distance")) if activity.get("distance") is not None else None,
        "kcal": float(activity.get("calories")) if activity.get("calories") is not None else None,
        "training_load": activity.get("activityTrainingLoad"),
        "avg_hr": activity.get("averageHR"),
        "max_hr": activity.get("maxHR"),
        "raw_json": activity,
    }


def _normalise_summary(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "steps": raw.get("totalSteps") or raw.get("steps"),
        "active_kcal": raw.get("activeKilocalories"),
        "resting_hr": raw.get("restingHeartRate"),
        "vo2max": raw.get("vo2Max"),
        "training_status": raw.get("trainingStatus"),
        # Instinct 3 等で取れる "屋外で動いた強度時間"。朝光暴露の補助 proxy
        "moderate_intensity_min": raw.get("moderateIntensityMinutes"),
        "vigorous_intensity_min": raw.get("vigorousIntensityMinutes"),
    }


def _normalise_hydration(raw: Any, target: date_type) -> dict[str, Any] | None:
    """Garmin Hydration API のレスポンスを正規化。

    レスポンス構造の例:
      ``{"calendarDate": "2026-05-06", "valueInML": 1500, "goalInML": 2500, ...}``
    """
    if not raw or not isinstance(raw, dict):
        return None
    value = raw.get("valueInML") or raw.get("hydrationInML") or raw.get("value")
    if value is None:
        return None
    try:
        value_ml = float(value)
    except (TypeError, ValueError):
        return None
    if value_ml <= 0:
        return None
    goal = raw.get("goalInML") or raw.get("goal")
    return {
        "value_ml": value_ml,
        "goal_ml": float(goal) if goal else None,
        "ts": datetime.combine(target, datetime.min.time()),
        "raw_json": raw,
    }


# Training Readiness の要因分解として raw_json に残すフィールド
_READINESS_FACTOR_KEYS = (
    "level",
    "feedbackShort",
    "sleepScore",
    "sleepScoreFactorPercent",
    "recoveryTime",
    "recoveryTimeFactorPercent",
    "acwrFactorPercent",
    "acuteLoad",
    "hrvFactorPercent",
    "hrvWeeklyAverage",
    "sleepHistoryFactorPercent",
    "stressHistoryFactorPercent",
)


def _normalise_training_readiness(raw: Any) -> dict[str, Any] | None:
    envelope = raw[0] if isinstance(raw, list) and raw else raw
    if not isinstance(envelope, dict):
        return None
    score = envelope.get("score")
    if score is None:
        return None
    factors = {k: envelope.get(k) for k in _READINESS_FACTOR_KEYS if envelope.get(k) is not None}
    return {"score": float(score), "factors": factors}


def _normalise_fitness_age(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    age = raw.get("fitnessAge")
    if age is None:
        return None
    return {
        "fitness_age": float(age),
        "raw": {
            k: raw.get(k)
            for k in ("chronologicalAge", "achievableFitnessAge", "previousFitnessAge")
            if raw.get(k) is not None
        },
    }


def _normalise_floors(raw: Any) -> dict[str, Any] | None:
    """floorValuesArray を descriptor で読み、floorsAscended の合計を返す。"""
    if not isinstance(raw, dict):
        return None
    descriptors = raw.get("floorsValueDescriptorDTOList") or []
    idx = None
    for d in descriptors:
        if isinstance(d, dict) and d.get("key") == "floorsAscended":
            idx = d.get("index")
            break
    if idx is None:
        return None
    total = 0.0
    for entry in raw.get("floorValuesArray") or []:
        if isinstance(entry, list) and len(entry) > idx and entry[idx] is not None:
            try:
                total += float(entry[idx])
            except (TypeError, ValueError):
                continue
    return {"ascended": total}


def _normalise_stress(raw: dict[str, Any]) -> list[dict[str, Any]]:
    arr: list[list[Any]] = raw.get("stressValuesArray") or []
    out: list[dict[str, Any]] = []
    for entry in arr:
        if len(entry) < 2:
            continue
        ts = _to_dt(entry[0])
        value = entry[1]
        if ts is None or value is None or value < 0:
            continue
        out.append({"ts": ts, "value": float(value)})
    return out

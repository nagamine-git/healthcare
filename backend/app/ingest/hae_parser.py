from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from dateutil import parser as date_parser

# Unit conversion helpers --------------------------------------------------


def _to_kg(qty: float, unit: str) -> float:
    u = unit.lower()
    if u in ("kg", "kilogram", "kilograms"):
        return qty
    if u in ("lb", "lbs", "pound", "pounds"):
        return qty * 0.45359237
    if u in ("g", "gram", "grams"):
        return qty / 1000.0
    return qty  # fallback: assume kg


def _to_meters(qty: float, unit: str) -> float:
    u = unit.lower()
    if u in ("km", "kilometer", "kilometers"):
        return qty * 1000.0
    if u in ("m", "meter", "meters"):
        return qty
    if u in ("mi", "mile", "miles"):
        return qty * 1609.344
    if u in ("ft", "feet"):
        return qty * 0.3048
    return qty


def _to_kcal(qty: float, unit: str) -> float:
    u = unit.lower()
    if u in ("kcal", "kilocalorie", "kilocalories"):
        return qty
    if u in ("kj", "kilojoule", "kilojoules"):
        return qty / 4.184
    return qty


def _parse_dt(value: str) -> datetime:
    """Parse HAE date strings into UTC datetimes."""
    dt = date_parser.parse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_dt_local(value: str) -> datetime:
    """Parse HAE date strings preserving the original timezone offset."""
    dt = date_parser.parse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# Normalised dataclasses ---------------------------------------------------


@dataclass
class NormalizedSample:
    source: str
    metric_key: str
    ts: datetime
    value: float | None
    unit: str | None
    raw: dict[str, Any] | None = None


@dataclass
class NormalizedWeight:
    ts: datetime
    weight_kg: float
    body_fat_pct: float | None
    muscle_kg: float | None
    water_pct: float | None
    source: str


@dataclass
class NormalizedSleep:
    date: date
    source: str
    total_min: int | None
    deep_min: int | None
    rem_min: int | None
    light_min: int | None
    awake_min: int | None
    sleep_score: float | None
    raw_json: dict[str, Any] | None = None


@dataclass
class NormalizedWorkout:
    id: str
    source: str
    start: datetime
    end: datetime | None
    type: str | None
    duration_s: int | None
    distance_m: float | None
    kcal: float | None
    avg_hr: float | None
    max_hr: float | None
    raw_json: dict[str, Any] | None = None


@dataclass
class ParseResult:
    samples: list[NormalizedSample] = field(default_factory=list)
    weights: list[NormalizedWeight] = field(default_factory=list)
    sleeps: list[NormalizedSleep] = field(default_factory=list)
    workouts: list[NormalizedWorkout] = field(default_factory=list)


# Parser -------------------------------------------------------------------


def parse_payload(payload: dict[str, Any]) -> ParseResult:
    data = payload.get("data") or {}
    metrics: Iterable[dict[str, Any]] = data.get("metrics") or []
    workouts: Iterable[dict[str, Any]] = data.get("workouts") or []

    result = ParseResult()

    # Aggregate per-day weight metrics so body_fat etc. can be merged.
    weight_by_ts: dict[datetime, dict[str, float]] = {}

    for metric in metrics:
        name = (metric.get("name") or "").strip()
        unit = metric.get("units") or ""
        rows: Iterable[dict[str, Any]] = metric.get("data") or []

        if name == "sleep_analysis":
            for row in rows:
                _ingest_sleep(row, result)
            continue

        if name == "weight_body_mass":
            for row in rows:
                ts = _parse_dt(row["date"])
                kg = _to_kg(float(row["qty"]), unit)
                weight_by_ts.setdefault(ts, {})["weight_kg"] = kg
            continue
        if name == "body_fat_percentage":
            for row in rows:
                ts = _parse_dt(row["date"])
                weight_by_ts.setdefault(ts, {})["body_fat_pct"] = float(row["qty"])
            continue
        if name == "lean_body_mass":
            for row in rows:
                ts = _parse_dt(row["date"])
                weight_by_ts.setdefault(ts, {})["muscle_kg"] = _to_kg(float(row["qty"]), unit)
            continue

        if name == "heart_rate":
            # row may have Min/Avg/Max keys
            for row in rows:
                ts = _parse_dt(row["date"])
                for key, suffix in (("Min", "min"), ("Avg", "avg"), ("Max", "max")):
                    if key in row and row[key] is not None:
                        result.samples.append(
                            NormalizedSample(
                                source="hae",
                                metric_key=f"heart_rate_{suffix}",
                                ts=ts,
                                value=float(row[key]),
                                unit=unit,
                                raw=row,
                            )
                        )
            continue

        # Default: scalar qty
        for row in rows:
            if "date" not in row:
                continue
            ts = _parse_dt(row["date"])
            qty = row.get("qty")
            normalised_value: float | None = None
            normalised_unit = unit
            if qty is None:
                pass
            elif name == "active_energy" or name == "dietary_energy":
                normalised_value = _to_kcal(float(qty), unit)
                normalised_unit = "kcal"
            elif name == "walking_running_distance":
                normalised_value = _to_meters(float(qty), unit)
                normalised_unit = "m"
            else:
                normalised_value = float(qty)

            result.samples.append(
                NormalizedSample(
                    source="hae",
                    metric_key=name,
                    ts=ts,
                    value=normalised_value,
                    unit=normalised_unit,
                    raw=row,
                )
            )

    for ts, fields in weight_by_ts.items():
        if "weight_kg" not in fields:
            continue
        result.weights.append(
            NormalizedWeight(
                ts=ts,
                weight_kg=fields["weight_kg"],
                body_fat_pct=fields.get("body_fat_pct"),
                muscle_kg=fields.get("muscle_kg"),
                water_pct=fields.get("water_pct"),
                source="hae",
            )
        )

    for w in workouts:
        result.workouts.append(_normalise_workout(w))

    return result


def _ingest_sleep(row: dict[str, Any], result: ParseResult) -> None:
    end_local = _parse_dt_local(row.get("endDate") or row.get("end") or row["date"])
    asleep_h = row.get("asleep")
    deep_h = row.get("deep")
    rem_h = row.get("rem")
    core_h = row.get("core") or row.get("light")
    awake_h = row.get("awake")
    total_min = int(asleep_h * 60) if asleep_h is not None else None
    sleep = NormalizedSleep(
        date=end_local.date(),
        source="hae",
        total_min=total_min,
        deep_min=int(deep_h * 60) if deep_h is not None else None,
        rem_min=int(rem_h * 60) if rem_h is not None else None,
        light_min=int(core_h * 60) if core_h is not None else None,
        awake_min=int(awake_h * 60) if awake_h is not None else None,
        sleep_score=None,
        raw_json=row,
    )
    result.sleeps.append(sleep)


def _normalise_workout(payload: dict[str, Any]) -> NormalizedWorkout:
    start = _parse_dt(payload.get("start") or payload.get("startDate") or payload["date"])
    end_raw = payload.get("end") or payload.get("endDate")
    end = _parse_dt(end_raw) if end_raw else None
    duration = payload.get("duration")
    distance = payload.get("distance") or {}
    energy = payload.get("activeEnergyBurned") or {}
    avg_hr_payload = payload.get("avgHeartRate") or {}
    max_hr_payload = payload.get("maxHeartRate") or {}

    distance_m: float | None = None
    if distance:
        distance_m = _to_meters(float(distance.get("qty", 0)), distance.get("units") or "")

    kcal: float | None = None
    if energy:
        kcal = _to_kcal(float(energy.get("qty", 0)), energy.get("units") or "")

    return NormalizedWorkout(
        id=f"hae-{payload.get('id') or start.isoformat()}",
        source="hae",
        start=start,
        end=end,
        type=payload.get("name"),
        duration_s=int(duration) if duration is not None else None,
        distance_m=distance_m,
        kcal=kcal,
        avg_hr=float(avg_hr_payload["qty"]) if avg_hr_payload else None,
        max_hr=float(max_hr_payload["qty"]) if max_hr_payload else None,
        raw_json=payload,
    )

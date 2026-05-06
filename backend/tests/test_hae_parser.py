from __future__ import annotations

from datetime import UTC, datetime

from app.ingest.hae_parser import (
    NormalizedSample,
    NormalizedSleep,
    NormalizedWeight,
    NormalizedWorkout,
    parse_payload,
)

# A small but realistic HAE-style payload.
SAMPLE_PAYLOAD = {
    "data": {
        "metrics": [
            {
                "name": "step_count",
                "units": "count",
                "data": [
                    {"qty": 1234, "date": "2026-05-01 10:00:00 +0900"},
                    {"qty": 5678, "date": "2026-05-01 18:00:00 +0900"},
                ],
            },
            {
                "name": "weight_body_mass",
                "units": "lb",
                "data": [{"qty": 154.32, "date": "2026-05-01 06:30:00 +0900"}],
            },
            {
                "name": "body_fat_percentage",
                "units": "%",
                "data": [{"qty": 18.4, "date": "2026-05-01 06:30:00 +0900"}],
            },
            {
                "name": "heart_rate",
                "units": "count/min",
                "data": [
                    {
                        "Min": 55,
                        "Avg": 70,
                        "Max": 130,
                        "date": "2026-05-01 12:00:00 +0900",
                    }
                ],
            },
            {
                "name": "sleep_analysis",
                "units": "hr",
                "data": [
                    {
                        "startDate": "2026-04-30 23:00:00 +0900",
                        "endDate": "2026-05-01 06:30:00 +0900",
                        "asleep": 6.5,
                        "inBed": 7.5,
                        "deep": 1.2,
                        "rem": 1.4,
                        "core": 3.4,
                        "awake": 0.5,
                        "source": "Apple Watch",
                    }
                ],
            },
            {
                "name": "dietary_energy",
                "units": "kcal",
                "data": [{"qty": 2200, "date": "2026-05-01 21:00:00 +0900"}],
            },
        ],
        "workouts": [
            {
                "id": "ABC-123",
                "name": "Running",
                "start": "2026-05-01 06:00:00 +0900",
                "end": "2026-05-01 06:45:00 +0900",
                "duration": 2700,
                "distance": {"qty": 7.5, "units": "km"},
                "activeEnergyBurned": {"qty": 420, "units": "kcal"},
                "avgHeartRate": {"qty": 145, "units": "count/min"},
                "maxHeartRate": {"qty": 168, "units": "count/min"},
            }
        ],
    }
}


def test_parse_payload_extracts_metric_samples():
    result = parse_payload(SAMPLE_PAYLOAD)
    keys = {s.metric_key for s in result.samples}
    assert "step_count" in keys
    assert "heart_rate_avg" in keys
    assert "heart_rate_min" in keys
    assert "heart_rate_max" in keys
    assert "dietary_energy" in keys


def test_parse_payload_normalises_weight_to_kg():
    result = parse_payload(SAMPLE_PAYLOAD)
    assert len(result.weights) == 1
    w: NormalizedWeight = result.weights[0]
    # 154.32 lb → ~70.0 kg
    assert 69.5 < w.weight_kg < 70.5
    assert w.body_fat_pct == 18.4
    assert w.source == "hae"


def test_parse_payload_extracts_sleep_session():
    result = parse_payload(SAMPLE_PAYLOAD)
    assert len(result.sleeps) == 1
    s: NormalizedSleep = result.sleeps[0]
    # Sleep belongs to the *wake* date (2026-05-01)
    assert s.date.isoformat() == "2026-05-01"
    assert s.total_min == int(6.5 * 60)
    assert s.deep_min == int(1.2 * 60)
    assert s.rem_min == int(1.4 * 60)
    assert s.awake_min == int(0.5 * 60)
    assert s.source == "hae"


def test_parse_payload_extracts_workouts():
    result = parse_payload(SAMPLE_PAYLOAD)
    assert len(result.workouts) == 1
    w: NormalizedWorkout = result.workouts[0]
    assert w.id == "hae-ABC-123"
    assert w.duration_s == 2700
    assert w.distance_m == 7500.0
    assert w.kcal == 420
    assert w.avg_hr == 145


def test_parse_payload_timestamps_are_utc_aware():
    result = parse_payload(SAMPLE_PAYLOAD)
    for s in result.samples:
        assert s.ts.tzinfo is not None
        assert s.ts.tzinfo.utcoffset(s.ts) == UTC.utcoffset(datetime.now(UTC))


def test_parse_payload_empty_returns_empty_lists():
    result = parse_payload({"data": {}})
    assert result.samples == []
    assert result.weights == []
    assert result.sleeps == []
    assert result.workouts == []


def test_normalized_sample_constructible():
    s = NormalizedSample(
        source="hae",
        metric_key="step_count",
        ts=datetime(2026, 5, 1, tzinfo=UTC),
        value=1000,
        unit="count",
        raw={"a": 1},
    )
    assert s.source == "hae"

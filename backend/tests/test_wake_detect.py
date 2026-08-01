from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.scoring.wake_detect import (
    ACTIVITY_THRESHOLD,
    SUSTAIN_MINUTES,
    detect_actual_wake,
    wake_stages,
    wake_stages_from_raw,
)


def _movement(start: datetime, levels: list[float]) -> list[dict]:
    """start から 1分刻みで levels を並べた sleepMovement 相当のリストを作る。"""
    out = []
    for i, level in enumerate(levels):
        s = start + timedelta(minutes=i)
        e = s + timedelta(minutes=1)
        out.append({
            "startGMT": s.strftime("%Y-%m-%dT%H:%M:%S.0"),
            "endGMT": e.strftime("%Y-%m-%dT%H:%M:%S.0"),
            "activityLevel": level,
        })
    return out


# 実データ相当: 睡眠終了 07:50 JST (=22:50 UTC 前日) 時点で activityLevel=2.6、
# 08:00 (=23:00 UTC、睡眠終了+10分) に 6.3 へ跳ね上がり、以降も高いまま。
def test_detects_actual_wake_real_data_like_case():
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)  # 07:50 JST
    start = sleep_end
    levels = [2.6] * 10 + [6.3, 6.5, 6.1]  # 22:50-22:59低体動 → 23:00に跳ね上がり持続
    movement = _movement(start, levels)

    wake = detect_actual_wake(movement, sleep_end)

    assert wake is not None
    # 23:00 UTC (=08:00 JST、睡眠終了+10分) で閾値超えが3分連続した最初の時刻
    assert wake == sleep_end + timedelta(minutes=10)


def test_no_sleep_movement_returns_none():
    """sleepMovement が無い夜は検出不能 → None (捏造しない)。"""
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    assert detect_actual_wake([], sleep_end) is None
    assert detect_actual_wake(None, sleep_end) is None


def test_never_reaches_threshold_returns_none():
    """窓の間ずっと閾値未満のまま終わる夜は検出不能 → None。"""
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    start = sleep_end - timedelta(minutes=10)
    levels = [1.0, 0.5, 2.0, 1.5, 3.8, 3.9, 2.0, 1.0, 0.5, 3.5, 2.2, 1.1, 0.9]
    movement = _movement(start, levels)

    assert detect_actual_wake(movement, sleep_end) is None


def test_single_spike_not_detected_as_wake():
    """連続3分に満たない単発スパイクは拾わない。"""
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    start = sleep_end - timedelta(minutes=5)
    # 単発スパイク (1分だけ閾値超え) → すぐ下がる。これを繰り返す。
    levels = [1.0, 1.2, 6.0, 1.0, 1.1, 6.5, 1.3, 0.9, 6.2, 1.0, 1.5]
    movement = _movement(start, levels)

    assert detect_actual_wake(movement, sleep_end) is None


def test_two_minute_spike_not_enough():
    """連続2分の高体動 (SUSTAIN_MINUTES=3 未満) は検出しない。"""
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    start = sleep_end
    levels = [5.0, 5.0, 0.5, 0.5, 0.5]
    movement = _movement(start, levels)

    assert detect_actual_wake(movement, sleep_end) is None


def test_outside_window_ignored():
    """探索窓の外 (睡眠終了 -90分より前 / +120分より後) の体動は無視する。"""
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    # 窓の外 (-91分) で高体動が3分続いても検出しない
    before = _movement(sleep_end - timedelta(minutes=91), [6.0, 6.0, 6.0])
    # 窓の外 (+121分) も同様
    after = _movement(sleep_end + timedelta(minutes=121), [6.0, 6.0, 6.0])
    assert detect_actual_wake(before, sleep_end) is None
    assert detect_actual_wake(after, sleep_end) is None


def test_gap_breaks_contiguity():
    """データが欠測して間隙が空いた場合は「連続」とみなさない。"""
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    m1 = {
        "startGMT": sleep_end.strftime("%Y-%m-%dT%H:%M:%S.0"),
        "endGMT": (sleep_end + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.0"),
        "activityLevel": 6.0,
    }
    # 5分後に再開 (欠測あり) → 連続とはみなさない
    gap_start = sleep_end + timedelta(minutes=6)
    m2 = _movement(gap_start, [6.0, 6.0])
    movement = [m1, *m2]
    assert detect_actual_wake(movement, sleep_end) is None


def test_wake_stages_computes_lingering_minutes():
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    start = sleep_end
    levels = [6.0, 6.0, 6.0]  # 睡眠終了ちょうどに検出 (lingering=0)
    movement = _movement(start, levels)

    out = wake_stages(movement, sleep_end)
    assert out["sleep_end_utc"] == sleep_end
    assert out["actual_wake_utc"] == sleep_end
    assert out["lingering_min"] == 0


def test_wake_stages_none_when_undetected():
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    out = wake_stages(None, sleep_end)
    assert out["sleep_end_utc"] == sleep_end
    assert out["actual_wake_utc"] is None
    assert out["lingering_min"] is None


def test_wake_stages_from_raw_uses_epoch_ms():
    """dailySleepDTO.sleepEndTimestampGMT は epoch ms (UTC) であることを確認。"""
    sleep_end = datetime(2026, 7, 30, 22, 50, 0)
    epoch_ms = int(sleep_end.replace(tzinfo=UTC).timestamp() * 1000)
    start = sleep_end + timedelta(minutes=10)
    raw = {
        "dailySleepDTO": {"sleepEndTimestampGMT": epoch_ms},
        "sleepMovement": _movement(start, [6.0, 6.0, 6.0]),
    }
    out = wake_stages_from_raw(raw)
    assert out is not None
    assert out["sleep_end_utc"] == sleep_end
    assert out["actual_wake_utc"] == start
    assert out["lingering_min"] == 10


def test_wake_stages_from_raw_none_without_sleep_end():
    assert wake_stages_from_raw(None) is None
    assert wake_stages_from_raw({}) is None
    assert wake_stages_from_raw({"dailySleepDTO": {}}) is None


def test_constants_match_verified_values():
    """ユーザー実データ検証済みの値からズレていないことを固定する回帰テスト。"""
    assert ACTIVITY_THRESHOLD == 4.0
    assert SUSTAIN_MINUTES == 3.0

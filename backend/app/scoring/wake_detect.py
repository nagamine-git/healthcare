"""「実際に動き出した起床時刻」を Garmin の体動 (sleepMovement) から検出する。

# 背景
Garmin の ``dailySleepDTO.sleepEndTimestampGMT`` (=睡眠終了) は「アルゴリズムが
睡眠段階の終わりと判定した時刻」であって、本人が布団から出た時刻ではない。
実際には睡眠終了後も布団でグダグダしている時間があり、これを「起床」扱いすると
朝の屋外光暴露の窓 (``morning_light.py``) 等がズレる。

# 実データで確認した事実 (2026-07 時点、本人の直近夜で検証)
``raw_json["sleepMovement"]`` は概ね 1 分刻みで 543 件/夜:
    {"startGMT": "2026-07-31T14:47:00.0", "endGMT": "...", "activityLevel": 5.71}
体動レベル (activityLevel) の分布: min=0.0 / 中央値=1.0 / 90%tile=3.8 / max=6.7。
直近 14 夜のうち、睡眠終了の前後 -90分〜+120分の窓で

    activityLevel >= 4.0 が連続3分続いた最初の時刻

を「起き上がった時刻」と定義すると 14 夜すべてで検出でき、睡眠終了との差
(=布団の中にいた時間) は中央値 +20分 (範囲 +1〜+55分) だった。
閾値を 8.0 にすると 14 夜中 0 夜も検出できなかった (90%tile=3.8 を大きく超えて
しまい、通常の寝返り程度の体動しか記録されない実データでは非現実的)。
4.0 は 90%tile よりわずかに高く、かつ実データで安定して検出できた値として採用する。

# タイムゾーン
- ``sleepMovement[].startGMT`` / ``endGMT`` は ``"%Y-%m-%dT%H:%M:%S.0"`` 形式の
  **UTC naive 文字列** (末尾の ``.0`` はミリ秒相当だが実質常に 0)。
- ``dailySleepDTO.sleepEndTimestampGMT`` は **epoch ミリ秒 (UTC)**。
両者は単位も表現形式も異なるので混ぜないこと。本モジュールの公開関数は
すべて「naive UTC の ``datetime``」に統一して受け渡しする。

# フォールバック方針
``sleepMovement`` が無い/短い/閾値に一度も達しない夜は **検出不能として None を
返す**。それらしい値を推定で埋めることはしない (捏造しない)。呼び出し側は
睡眠終了時刻へフォールバックすること。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# 体動レベルの閾値。実データ分布 (中央値1.0/90%tile 3.8) に対し、8.0 では
# 14 夜中 0 夜も検出できなかった実績を踏まえ 4.0 を採用 (根拠は上記モジュール docstring)。
ACTIVITY_THRESHOLD = 4.0

# 「起き上がった」とみなす連続時間 (分)。1分程度の単発スパイク (寝返り) を
# 誤検出しないための最小限。実データでは 3 分で 14 夜すべて検出できた。
SUSTAIN_MINUTES = 3.0

# 睡眠終了の前後どこまでを探索するか (実データで検出できた時刻はすべて
# 睡眠終了 +1〜+55分だったが、早めの目覚め (アラーム前に起きて再び横になる等) も
# 拾えるよう前方にも余裕を持たせる)。
WINDOW_BEFORE_MIN = 90
WINDOW_AFTER_MIN = 120

# サンプル間の連続性判定の許容誤差 (秒)。sleepMovement は概ね1分刻みで
# endGMT == 次の startGMT だが、欠測分があった場合は連続とみなさない
# (実測にない間隙を「継続している」と推定しないため)。
_CONTIGUOUS_TOLERANCE_SEC = 90.0

_GMT_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def _parse_gmt(value: Any) -> datetime | None:
    """``"2026-07-31T14:47:00.0"`` (UTC naive) を ``datetime`` に変換。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _GMT_FORMAT)
    except ValueError:
        return None


def detect_actual_wake(
    sleep_movement: list[dict[str, Any]] | None,
    sleep_end_utc: datetime,
) -> datetime | None:
    """体動データから「起き上がった時刻」(naive UTC) を検出する。

    睡眠終了 (``sleep_end_utc``) の前後 [-WINDOW_BEFORE_MIN, +WINDOW_AFTER_MIN] 分の
    窓の中で、``activityLevel >= ACTIVITY_THRESHOLD`` が連続 ``SUSTAIN_MINUTES`` 分
    続いた最初のサンプルの開始時刻を返す。検出できなければ ``None``
    (=呼び出し側で睡眠終了時刻にフォールバックすること。捏造しない)。
    """
    if not sleep_movement:
        return None

    window_start = sleep_end_utc - timedelta(minutes=WINDOW_BEFORE_MIN)
    window_end = sleep_end_utc + timedelta(minutes=WINDOW_AFTER_MIN)

    samples: list[tuple[datetime, datetime, float]] = []
    for entry in sleep_movement:
        if not isinstance(entry, dict):
            continue
        start = _parse_gmt(entry.get("startGMT"))
        if start is None or start < window_start or start >= window_end:
            continue
        level_raw = entry.get("activityLevel")
        try:
            level = float(level_raw)
        except (TypeError, ValueError):
            continue
        end = _parse_gmt(entry.get("endGMT")) or (start + timedelta(minutes=1))
        samples.append((start, end, level))

    samples.sort(key=lambda t: t[0])

    run_start: datetime | None = None
    run_elapsed_min = 0.0
    prev_end: datetime | None = None
    for start, end, level in samples:
        is_high = level >= ACTIVITY_THRESHOLD
        contiguous = (
            prev_end is not None
            and (start - prev_end).total_seconds() <= _CONTIGUOUS_TOLERANCE_SEC
        )
        if is_high and run_start is not None and contiguous:
            run_elapsed_min += (end - start).total_seconds() / 60.0
        elif is_high:
            run_start = start
            run_elapsed_min = (end - start).total_seconds() / 60.0
        else:
            run_start = None
            run_elapsed_min = 0.0

        if run_start is not None and run_elapsed_min >= SUSTAIN_MINUTES:
            return run_start

        prev_end = end

    return None


def wake_stages(
    sleep_movement: list[dict[str, Any]] | None,
    sleep_end_utc: datetime,
) -> dict[str, Any]:
    """「目覚め (睡眠終了)」と「起床 (体動確認)」の2段階、その差を返す。

    Returns:
        {
            "sleep_end_utc": datetime,               # naive UTC、睡眠終了 (Garmin判定)
            "actual_wake_utc": datetime | None,       # naive UTC、体動から検出した起床。検出不能なら None
            "lingering_min": int | None,              # 布団の中にいた時間 (分)。actual_wake が None なら None
        }
    """
    actual_wake = detect_actual_wake(sleep_movement, sleep_end_utc)
    lingering_min = (
        round((actual_wake - sleep_end_utc).total_seconds() / 60.0)
        if actual_wake is not None
        else None
    )
    return {
        "sleep_end_utc": sleep_end_utc,
        "actual_wake_utc": actual_wake,
        "lingering_min": lingering_min,
    }


def wake_stages_from_raw(raw_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """``SleepSession.raw_json`` から直接 ``wake_stages()`` を計算する便利関数。

    ``dailySleepDTO.sleepEndTimestampGMT`` (epoch ms) が無ければ睡眠終了時刻
    そのものが不明なので ``None`` を返す (呼び出し側は SleepSession の他フィールド
    等、既存のフォールバックへ委ねること)。
    """
    if not raw_json:
        return None
    dto = raw_json.get("dailySleepDTO") or {}
    end_ms = dto.get("sleepEndTimestampGMT")
    if not isinstance(end_ms, (int, float)):
        return None
    sleep_end_utc = datetime.fromtimestamp(float(end_ms) / 1000.0, tz=UTC).replace(tzinfo=None)
    movement = raw_json.get("sleepMovement")
    return wake_stages(movement if isinstance(movement, list) else None, sleep_end_utc)

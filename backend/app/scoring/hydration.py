"""飲水量の単一の解決先。

同じ生理量 (その日に飲んだ水分) が 3 つの ``metric_key`` に分かれて入っている:

- ``garmin_hydration_ml``  純正 Hydration アプリ。**1 日 1 行の累積スナップショット**。
  ``ts`` は同期時刻であって飲んだ時刻ではない (実測では毎日 09:00 に 1 行)
- ``tide_hydration_ml``    TIDE ウォッチアプリ。**1 タップ 1 行のイベント**。
  ``ts`` は実際に飲んだ時刻
- ``dietary_water``        Apple Health 経由 (Ascend)

**前 2 つは足す。** 独立した記録経路なので合計が実際の飲水量になる
(同じ一杯を両方のアプリに入れた時だけ二重になるが、それは入力側の問題)。

**``dietary_water`` は足さない。** Ascend が TIDE の水分を Apple Health に書き戻すため、
足すと TIDE 分が二重に乗る。一次ソースが両方とも空の日に限りフォールバックに使う。

⚠️ **「記録が無い日」と「飲まなかった日」を混同しないこと。** 合計 0 はほぼ前者で、
0 を実測値として分析に流すと偽の脱水日を量産する。``daily_ml`` / ``daily_map`` は
記録が無い日を ``None`` / 欠損として返し、呼び出し側で除外できるようにしてある。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import func, select

from app.models import MetricSample

# 独立した一次ソース。合計がその日の飲水量になる
PRIMARY_KEYS: tuple[str, ...] = ("garmin_hydration_ml", "tide_hydration_ml")
# 一次ソースが空の日だけ使う。TIDE の書き戻しを含むため一次と足してはいけない
FALLBACK_KEY = "dietary_water"

# これ未満はログ無し扱い (コップ半分未満を「その日の全摂取」とは読まない)。
# nutrition.py が水分に使っていた閾値と揃えてある
MIN_LOGGED_ML = 100.0


def key_predicate(keys: str | tuple[str, ...] | list[str]):
    """``metric_key`` の一致条件。単一キーと複数キーのどちらも受ける。"""
    if isinstance(keys, str):
        return MetricSample.metric_key == keys
    return MetricSample.metric_key.in_(tuple(keys))


def daily_ml(session, start: datetime, end: datetime) -> float | None:
    """[start, end) の飲水量 (mL)。記録が無ければ ``None``。

    ``start``/``end`` は UTC naive (DB と同じ)。JST の暦日で欲しい場合は
    呼び出し側で ``jst_day_bounds`` を通すこと。
    """
    val = session.execute(
        select(func.sum(MetricSample.value)).where(
            key_predicate(PRIMARY_KEYS),
            MetricSample.ts >= start,
            MetricSample.ts < end,
        )
    ).scalar()
    if val is not None and float(val) >= MIN_LOGGED_ML:
        return float(val)

    fb = session.execute(
        select(func.sum(MetricSample.value)).where(
            MetricSample.metric_key == FALLBACK_KEY,
            MetricSample.ts >= start,
            MetricSample.ts < end,
        )
    ).scalar()
    if fb is not None and float(fb) >= MIN_LOGGED_ML:
        return float(fb)
    return None


def daily_map(session, start: datetime, end: datetime) -> dict[date_type, float]:
    """JST 暦日 → その日の飲水量 (mL)。**記録の無い日はキーごと存在しない。**

    「0 mL の日」を作らないのが要点。分析側が ``.get(d)`` で ``None`` を受け取り、
    そのアンカーを除外できるようにするため。
    """
    jst_date = func.date(MetricSample.ts, "+9 hours")
    rows = session.execute(
        select(jst_date, func.sum(MetricSample.value))
        .where(
            key_predicate(PRIMARY_KEYS),
            MetricSample.ts >= start,
            MetricSample.ts < end,
        )
        .group_by(jst_date)
    ).all()

    out: dict[date_type, float] = {}
    for d, s in rows:
        if s is None or float(s) < MIN_LOGGED_ML:
            continue
        out[_as_date(d)] = float(s)

    # 一次ソースが無い日だけ Apple Health で埋める (足さない)
    fb_rows = session.execute(
        select(jst_date, func.sum(MetricSample.value))
        .where(
            MetricSample.metric_key == FALLBACK_KEY,
            MetricSample.ts >= start,
            MetricSample.ts < end,
        )
        .group_by(jst_date)
    ).all()
    for d, s in fb_rows:
        if s is None or float(s) < MIN_LOGGED_ML:
            continue
        out.setdefault(_as_date(d), float(s))
    return out


def events(session, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """実際に飲んだ時刻つきの飲水イベント [(ts, mL), ...]。**TIDE のみ**。

    ``garmin_hydration_ml`` は 1 日 1 行のスナップショットで ``ts`` が同期時刻なので、
    時刻分解能が要る用途 (摂取カーブ・発症前ウィンドウの切り出し) には使えない。
    TIDE で記録した日だけ真の時系列が取れる。
    """
    rows = session.execute(
        select(MetricSample.ts, MetricSample.value)
        .where(
            MetricSample.metric_key == "tide_hydration_ml",
            MetricSample.ts >= start,
            MetricSample.ts < end,
            MetricSample.value.isnot(None),
        )
        .order_by(MetricSample.ts)
    ).all()
    return [(ts, float(v)) for ts, v in rows]


# ⚠️ 以下 4 定数は TIDE 側 (garmin-tide/source/Model.mc) と同じ値であること。
# ズレると時計とサーバーで違う目標が出てユーザーが混乱する
ML_PER_KG = 32.0        # 総水分の目安 (成人 30-35 mL/kg/日 の中央値)
FOOD_FRACTION = 0.25    # 食品由来が占める割合 → 飲料目標は残り 75%
FLOOR_MALE_ML = 1800    # EFSA 2.5 L/日 から食品由来を引いた飲料目標の下限
FLOOR_OTHER_ML = 1400   # 同 2.0 L/日


def goal_ml(weight_kg: float | None, sweat_ml: float = 0.0, *, sex: str | None = None) -> int:
    """その日の飲水目標 (mL)。

    体重あたりの総水分必要量 (成人で 30-35 mL/kg/日) から **食品由来の約 25%** を
    引いた分が、飲料で摂るべき量になる。下限は EFSA の適正摂取量から引いた値。

    発汗損失は補填が必要なので上乗せする (ACSM の水分補給指針の考え方。
    Garmin も純正 Hydration の目標を ``sweatLossInML`` で同様に押し上げている)。
    ここが純正アプリに唯一劣っていた点で、TIDE 単体では発汗を知りようがないため
    サーバーが計算して同期レスポンスで返す。
    """
    w = weight_kg or 60.0
    base = w * ML_PER_KG * (1.0 - FOOD_FRACTION)
    floor = FLOOR_MALE_ML if (sex or "").lower().startswith("m") else FLOOR_OTHER_ML
    if base < floor:
        base = float(floor)
    return int(round(base + max(0.0, sweat_ml)))


def _as_date(v) -> date_type:
    """SQLite の ``date()`` は文字列を返すので ``date`` に揃える。"""
    if isinstance(v, date_type) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def latest_sweat_ml(session, start: datetime, end: datetime) -> float:
    """その日の発汗損失 (mL)。Garmin の実測 ``sweatLossInML``。無ければ 0。"""
    import json as _json

    row = session.execute(
        select(MetricSample.raw_json)
        .where(
            MetricSample.metric_key == "garmin_hydration_ml",
            MetricSample.ts >= start,
            MetricSample.ts < end,
        )
        .order_by(MetricSample.ts.desc())
        .limit(1)
    ).first()
    if not row:
        return 0.0
    raw = row[0]
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except Exception:
            return 0.0
    if not isinstance(raw, dict):
        return 0.0
    try:
        return float(raw.get("sweatLossInML") or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "FALLBACK_KEY",
    "MIN_LOGGED_ML",
    "PRIMARY_KEYS",
    "daily_map",
    "daily_ml",
    "events",
    "goal_ml",
    "key_predicate",
    "latest_sweat_ml",
]

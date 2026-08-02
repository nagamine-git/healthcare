"""compute_tonight_plan: 深夜0時台〜起床前に呼ばれた時の日付・sleep_now ロジック。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.scoring.sleep_plan import compute_tonight_plan

JST = ZoneInfo("Asia/Tokyo")

# デフォルト設定: wake_time=06:30, target_sleep_min=480 (8h)。DB にプロフィール行が無いので
# resolve_profile はこの既定値を使う。
TARGET = date(2026, 7, 20)


def _seed_habitual_phase(session, *, mid_hour: float, dur_min: int) -> None:
    """_habitual_phase が拾う「習慣的な就寝」データを1件だけ仕込む (median = その値)。"""
    from app.models import MetricSample, SleepSession

    session.add(SleepSession(date=TARGET - timedelta(days=1), source="garmin", total_min=dur_min))
    session.add(MetricSample(
        source="garmin", metric_key="sleep_midpoint_hour",
        ts=datetime.combine(TARGET - timedelta(days=1), datetime.min.time()) + timedelta(hours=20),
        value=mid_hour,
    ))
    session.commit()


def test_evening_call_plans_for_tomorrow_morning(db_engine):
    # 夜 20:00 に呼ぶ通常ケース: 起床は「翌日」の朝になる (従来通り、habitual補正なし)。
    now = datetime(2026, 7, 20, 20, 0, tzinfo=JST)
    plan = compute_tonight_plan(TARGET, now=now)
    assert plan["wake"] == "06:30"
    assert plan["sleep_now"] is False
    assert plan["estimated_sleep_min"] == 480


def test_early_morning_before_wake_uses_todays_wake_not_tomorrows(db_engine):
    # 深夜 00:10 に呼んだ場合、起床は「target 自身の朝」であって target+1 の翌朝ではない
    # (バグ修正の核心)。habitual補正が無いデフォルトでは理想就寝(22:30・前夜)はすでに
    # 過ぎているので sleep_now は True になる。
    now = datetime(2026, 7, 20, 0, 10, tzinfo=JST)
    plan = compute_tonight_plan(TARGET, now=now)
    assert plan["wake"] == "06:30"  # target+1 (07-21) ではなく target (07-20) 自身の朝
    assert plan["sleep_now"] is True


def test_habitual_bedtime_after_midnight_not_yet_passed(db_engine, session):
    # 習慣的な就寝が 01:42・睡眠5.7h (ユーザー実データを模した値) だと、概日前進の上限
    # (45分) で 00:57 に丸められる。00:10 時点ではまだその就寝目標前 → sleep_now False。
    _seed_habitual_phase(session, mid_hour=4.55, dur_min=342)
    now = datetime(2026, 7, 20, 0, 10, tzinfo=JST)
    plan = compute_tonight_plan(TARGET, now=now)
    assert plan["wake"] == "06:30"
    assert plan["bedtime"] == "00:57"
    assert plan["sleep_now"] is False
    assert plan["estimated_sleep_min"] == 5 * 60 + 33  # 00:57 → 06:30


def test_habitual_bedtime_after_midnight_now_passed_triggers_sleep_now(db_engine, session):
    # 同じ状況で 01:14 (=就寝目標00:57 を17分過ぎた) に呼ぶと、今すぐ寝るべき局面になり、
    # 目安睡眠は「今から寝た場合」に現在時刻起点で補正される (単純な固定値ではない)。
    _seed_habitual_phase(session, mid_hour=4.55, dur_min=342)
    now = datetime(2026, 7, 20, 1, 14, tzinfo=JST)
    plan = compute_tonight_plan(TARGET, now=now)
    assert plan["sleep_now"] is True
    assert plan["compressed"] is True
    assert plan["estimated_sleep_min"] == 5 * 60 + 16  # 01:14 → 06:30
    assert "今すぐ寝てください" in plan["notes"][0]


def test_sleep_now_false_once_past_wake_time(db_engine):
    # 起床時刻(06:30)を過ぎたら「今夜」は次の日の夜の計画に戻る (sleep_now は解除)。
    now = datetime(2026, 7, 20, 7, 0, tzinfo=JST)
    plan = compute_tonight_plan(TARGET, now=now)
    assert plan["sleep_now"] is False
    assert plan["wake"] == "06:30"  # 翌日 (target+1) の朝


# ----- 日別の起床時刻オーバーライド -----


def _put_override(session, d: date, hhmm: str) -> None:
    from app.models import SleepPlanOverride

    session.add(SleepPlanOverride(date=d, wake_time=hhmm, updated_at=datetime(2026, 7, 20, 12, 0)))
    session.commit()


def test_override_shifts_wake_and_bedtime(session):
    """その日だけの起床時刻が計画全体を動かす (就寝も締切も追随する)。"""
    base = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 20, 0, tzinfo=JST))
    # 既定では起床は翌朝 (TARGET+1)
    _put_override(session, TARGET + timedelta(days=1), "05:00")
    got = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 20, 0, tzinfo=JST))

    assert base["wake"] != got["wake"]
    assert got["wake"] == "05:00"
    assert got["wake_overridden"] is True
    # 逆算されるものが前倒しになる (就寝・カフェイン締切とも)
    assert got["ideal_bedtime"] < base["ideal_bedtime"]
    assert got["caffeine_cutoff_time"] != base["caffeine_cutoff_time"]


def test_override_keyed_by_wake_date_across_midnight(session):
    """深夜0時台に呼ぶと「その朝」が起床日。オーバーライドはその日付で引かれる。

    既存の in_progress_night 判定と引き当てキーが一致していることの回帰テスト。
    """
    # TARGET 当日の朝を上書き。深夜 1:00 に呼べば「まだ TARGET の朝を迎えていない」ので効く
    _put_override(session, TARGET, "05:00")
    got = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 1, 0, tzinfo=JST))
    assert got["wake"] == "05:00"
    assert got["wake_overridden"] is True


def test_past_override_is_ignored(session):
    """起床時刻を過ぎた上書きは無視され、次の起床 (既定) が使われる。"""
    _put_override(session, TARGET, "05:00")
    # 09:00 時点では TARGET 05:00 は過ぎている → 翌朝の既定 (06:30) を見る
    got = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 9, 0, tzinfo=JST))
    assert got["wake"] == "06:30"
    assert got["wake_overridden"] is False


def test_no_override_keeps_default(session):
    got = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 20, 0, tzinfo=JST))
    assert got["wake"] == "06:30"
    assert got["wake_overridden"] is False


def test_cutoff_times_are_derived_from_bedtime(session):
    """追加した逆算項目が bedtime から正しい差分になっていること。"""
    from app.config import get_settings

    got = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 20, 0, tzinfo=JST))
    s = get_settings()

    def _mins(hhmm: str) -> int:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    bed = _mins(got["bedtime"])
    # 日跨ぎを吸収するため mod 1440 で比較する
    assert (bed - _mins(got["caffeine_cutoff_time"])) % 1440 == int(
        s.caffeine_cutoff_hours_before_bed * 60)
    assert (bed - _mins(got["exercise_cutoff_time"])) % 1440 == s.exercise_to_bed_lead_min
    assert (bed - _mins(got["dim_light_time"])) % 1440 == s.dim_light_lead_min


# ---------------------------------------------------------------------------
# 「起床」= 布団から出る時刻。逆算のアンカーは睡眠終了 (= 起床 − 布団の中)
# ---------------------------------------------------------------------------


def _seed_lingering(
    session, *, days: int, sleep_end_jst_h: int, lingering_min: int, offset: int = 0
) -> None:
    """体動から `lingering_min` 分の「布団の中」が検出できる夜を days 夜ぶん仕込む。

    offset は TARGET から何日遡って始めるか (sleep_session.date は UNIQUE なので、
    複数回呼ぶときは日付が重ならないようずらすこと)。
    """
    from datetime import UTC

    from app.models import SleepSession

    for i in range(1 + offset, days + 1 + offset):
        d = TARGET - timedelta(days=i)
        # 睡眠終了 (JST) → epoch ms (UTC)
        end_jst = datetime.combine(d, datetime.min.time(), JST) + timedelta(hours=sleep_end_jst_h)
        end_utc = end_jst.astimezone(UTC).replace(tzinfo=None)
        movement = []
        # 睡眠終了から lingering_min 分は低体動、その後3分以上 閾値超えを続ける
        for m in range(lingering_min + 5):
            s = end_utc + timedelta(minutes=m)
            movement.append({
                "startGMT": s.strftime("%Y-%m-%dT%H:%M:%S.0"),
                "endGMT": (s + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.0"),
                "activityLevel": 1.0 if m < lingering_min else 6.0,
            })
        session.add(SleepSession(
            date=d, source="garmin", total_min=342,
            raw_json={
                "dailySleepDTO": {"sleepEndTimestampGMT": int(end_jst.timestamp() * 1000)},
                "sleepMovement": movement,
            },
        ))
    session.commit()


def test_backcalc_anchors_on_sleep_end_not_out_of_bed(db_engine, session):
    """布団の中 20分なら、逆算の基準は起床 06:30 ではなく目覚め 06:10 になる。

    起床時刻をそのままアンカーにすると、布団でグダグダしている20分を睡眠として
    数えてしまい、必要睡眠 8h を確保できない就寝時刻を「理想」と呼んでしまう。
    """
    _seed_lingering(session, days=5, sleep_end_jst_h=6, lingering_min=20)
    plan = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 20, 0, tzinfo=JST))

    assert plan["wake"] == "06:30"          # 布団から出る時刻 (表示上の「起床」)
    assert plan["lingering_min"] == 20
    assert plan["sleep_end"] == "06:10"     # 逆算のアンカー
    assert plan["ideal_bedtime"] == "22:10"  # 06:10 − 8h (06:30 − 8h = 22:30 ではない)
    assert plan["estimated_sleep_min"] == 480


def test_morning_light_window_still_anchored_on_out_of_bed(db_engine, session):
    """朝の光浴だけは「布団から出る時刻」が基準 (布団の中では屋外光を浴びられない)。"""
    _seed_lingering(session, days=5, sleep_end_jst_h=6, lingering_min=20)
    plan = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 20, 0, tzinfo=JST))

    assert plan["morning_light"] == {"start": "06:30", "end": "07:00"}


def test_no_movement_data_falls_back_to_wake_time(db_engine, session):
    """体動から1夜も検出できなければ従来どおり起床時刻をそのまま逆算に使う (捏造しない)。"""
    plan = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 20, 0, tzinfo=JST))

    assert plan["lingering_min"] is None
    assert plan["sleep_end"] == plan["wake"] == "06:30"
    assert plan["ideal_bedtime"] == "22:30"


def test_lingering_uses_median_and_ignores_outliers(db_engine, session):
    """外れ値混じりでも median を採り、上限 (_MAX_LINGERING_MIN) 超えは捨てる。"""
    from app.scoring.sleep_plan import _MAX_LINGERING_MIN, _habitual_lingering_min

    _seed_lingering(session, days=3, sleep_end_jst_h=6, lingering_min=15)
    # 上限を超える異常な夜を1つ足しても median は 15 のまま (異常夜は除外される)
    _seed_lingering(
        session, days=1, sleep_end_jst_h=3,
        lingering_min=_MAX_LINGERING_MIN + 30, offset=3,
    )

    assert _habitual_lingering_min(TARGET) == 15


def test_sleep_now_window_ends_at_sleep_end(db_engine, session):
    """睡眠終了〜起床 (布団の中) の時間帯は「今すぐ寝るべき」ではない。"""
    _seed_lingering(session, days=5, sleep_end_jst_h=6, lingering_min=20)
    # 06:20 = 目覚め 06:10 を過ぎ、布団から出る 06:30 の前
    plan = compute_tonight_plan(TARGET, now=datetime(2026, 7, 20, 6, 20, tzinfo=JST))

    assert plan["sleep_now"] is False

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.db import session_scope
from app.models import AlcoholIntake, BodyBatteryDaily, MetricSample, SleepSession
from app.scoring import sleep_drivers as sd


def test_accumulating_below_min(db_engine):
    today = date(2026, 6, 15)
    with session_scope() as s:
        for i in range(3):
            d = today - timedelta(days=i)
            s.add(SleepSession(date=d, source="garmin", total_min=420, awake_min=30, sleep_score=70))
    out = sd.analyze(today)
    assert out["status"] == "accumulating"
    assert out["n_nights"] == 3


def test_alcohol_lowers_efficiency(db_engine):
    """夜に飲酒した夜は睡眠効率が低い → alcohol_eve が悪化方向で出る。"""
    today = date(2026, 6, 15)
    with session_scope() as s:
        for i in range(1, 41):
            d = today - timedelta(days=i)
            drank = i % 2 == 0
            # 飲酒夜は効率85、非飲酒夜は効率95 (awake_min で差をつける)
            awake = 75 if drank else 22
            s.add(SleepSession(date=d, source="garmin", total_min=420, awake_min=awake, sleep_score=70))
            if drank:
                # 前日(d-1)の夜 20:00 に飲酒
                ts = datetime.combine(d - timedelta(days=1), datetime.min.time()).replace(hour=11)  # JST20:00=UTC11:00
                s.add(AlcoholIntake(ts=ts, source="beer", grams=20.0))
    out = sd.analyze(today)
    assert out["status"] == "analyzed"
    alc = next((f for f in out["quality"] if f["driver"] == "alcohol_eve" and f["outcome"] == "efficiency"), None)
    assert alc is not None, out["quality"]
    assert alc["direction"] == "悪化"
    assert alc["tier"] in ("strong", "suggestive", "trend")


def test_preliminary_signal_below_gate(db_engine):
    """8夜未満 (ゲート未達) でも各群>=2あれば暫定シグナル (方向+効果量) を出す。"""
    today = date(2026, 6, 15)
    with session_scope() as s:
        for i in range(1, 6):  # 5夜
            d = today - timedelta(days=i)
            drank = i % 2 == 0  # i=2,4 の 2 夜
            awake = 75 if drank else 22
            s.add(SleepSession(date=d, source="garmin", total_min=420, awake_min=awake, sleep_score=70))
            if drank:
                ts = datetime.combine(d - timedelta(days=1), datetime.min.time()).replace(hour=11)
                s.add(AlcoholIntake(ts=ts, source="beer", grams=20.0))
    out = sd.analyze(today)
    assert out["status"] == "preliminary"
    alc = next(
        (f for f in out["quality"] if f["driver"] == "alcohol_eve" and f["outcome"] == "efficiency"),
        None,
    )
    assert alc is not None, out
    assert alc["tier"] == "preliminary"
    assert alc["direction"] == "悪化"


def test_morning_light_predicts_sleep_score(db_engine):
    """前日朝によく歩いた(=光を浴びた proxy)夜ほど睡眠スコアが良い → morning_light が改善方向。"""
    today = date(2026, 6, 15)
    tz = ZoneInfo("Asia/Tokyo")
    with session_scope() as s:
        for i in range(1, 41):
            d = today - timedelta(days=i)
            prev = d - timedelta(days=1)
            bright = i % 2 == 0
            score = 85 if bright else 55
            s.add(SleepSession(date=d, source="garmin", total_min=420, awake_min=30, sleep_score=score))
            # 前日(prev) 06:30 JST (起床想定) から3h以内に歩数を計上 = 朝の光 proxy
            wake_utc = datetime(prev.year, prev.month, prev.day, 6, 30, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
            steps_val = 4000.0 if bright else 100.0
            s.add(MetricSample(source="test", metric_key="steps", ts=wake_utc + timedelta(hours=1), value=steps_val))
    out = sd.analyze(today)
    assert out["status"] == "analyzed"
    ml = next(
        (f for f in out["quality"] if f["driver"] == "morning_light" and f["outcome"] == "sleep_score"),
        None,
    )
    assert ml is not None, out["quality"]
    assert ml["direction"] == "改善"


def test_alcohol_worsens_restlessness(db_engine):
    """夜に飲酒した夜は体動が多い(=restlessness_inv は悪化方向、符号反転の確認)。"""
    today = date(2026, 6, 15)
    with session_scope() as s:
        for i in range(1, 41):
            d = today - timedelta(days=i)
            drank = i % 2 == 0
            s.add(SleepSession(date=d, source="garmin", total_min=420, awake_min=30, sleep_score=70))
            # 体動回数 (生値): 飲酒夜は多い(悪い)、非飲酒夜は少ない(良い)
            restless_val = 40.0 if drank else 8.0
            ts = datetime.combine(d, datetime.min.time()).replace(hour=7)
            s.add(MetricSample(source="garmin", metric_key="sleep_restless_moments", ts=ts, value=restless_val))
            if drank:
                alc_ts = datetime.combine(d - timedelta(days=1), datetime.min.time()).replace(hour=11)
                s.add(AlcoholIntake(ts=alc_ts, source="beer", grams=20.0))
    out = sd.analyze(today)
    assert out["status"] == "analyzed"
    r = next(
        (f for f in out["quality"] if f["driver"] == "alcohol_eve" and f["outcome"] == "restlessness_inv"),
        None,
    )
    assert r is not None, out["quality"]
    # 飲酒夜(体動多い=restlessness_inv低い)が「悪化」方向で出ることを確認
    assert r["direction"] == "悪化"


def test_duration_excluded_from_restlessness(db_engine):
    """睡眠時間が長いほど体動の絶対回数が増える自明の関係を duration ドライバーの
    対象から除外していること (efficiency 等の既存除外と同じ理由)。ここでは duration と
    restlessness_inv がわざと強く相関するデータを用意し、それでも quality の
    duration×restlessness_inv 行が出ないことを確認する。"""
    today = date(2026, 6, 15)
    with session_scope() as s:
        for i in range(1, 41):
            d = today - timedelta(days=i)
            long_night = i % 2 == 0
            total = 480 if long_night else 300
            s.add(SleepSession(date=d, source="garmin", total_min=total, awake_min=30, sleep_score=70))
            # 長く寝た夜ほど体動の絶対回数(生値)も多い、という自明の関係を再現
            restless_val = 60.0 if long_night else 10.0
            ts = datetime.combine(d, datetime.min.time()).replace(hour=7)
            s.add(MetricSample(source="garmin", metric_key="sleep_restless_moments", ts=ts, value=restless_val))
            # duration が全く何とも比較されないと tests が空になってしまうため、
            # duration×next_day (除外対象外) を成立させる目的でのみ翌朝BBを入れる
            s.add(BodyBatteryDaily(date=d, morning_value=70.0 if long_night else 50.0))
    out = sd.analyze(today)
    assert out["status"] == "analyzed"
    dur_vs_restless = next(
        (f for f in out["quality"] if f["driver"] == "duration" and f["outcome"] == "restlessness_inv"),
        None,
    )
    assert dur_vs_restless is None, out["quality"]
    # duration 自体は次日アウトカムに対しては引き続きテストされていることの確認
    # (除外がドライバー全体でなく quality グループ限定であることの検証)
    dur_vs_bb = next(
        (f for f in out["next_day"] if f["driver"] == "duration" and f["outcome"] == "morning_bb"),
        None,
    )
    assert dur_vs_bb is not None, out["next_day"]


# ----- ラベルと助言文が実体と一致していること -----


def test_driver_labels_name_the_actual_metric():
    """「活動量」「運動量」のような曖昧な語を使わない。

    どちらが歩数でどちらがワークアウト負荷か利用者が判別できなかったため、
    ラベルは実体そのもの (歩数 / ワークアウト負荷) を書く。
    """
    from app.scoring.sleep_drivers import _DRIVERS

    labels = dict(_DRIVERS)
    assert labels["steps"] == "日中の歩数"
    assert labels["exercise"] == "ワークアウト負荷"


def test_steps_advice_is_about_steps_not_intensity():
    """歩数ドライバーの助言が「高強度運動を避ける」にすり替わらないこと。

    回帰テスト: steps (歩数) の悪化側に exercise 用の文言が入っており、
    歩数の話が運動強度の話になっていた。
    """
    from app.scoring.sleep_drivers import _action_text

    anchors = {"bedtime": "00:55", "exercise_cutoff": "21:55",
               "caffeine_cutoff": "18:55", "alcohol_cutoff": "21:55",
               "dur_h": 7.0, "steps_median": 4592}

    good = _action_text("steps", "改善", anchors)
    assert "歩" in good
    assert "4,592" in good          # 目標が具体的な歩数で出る
    assert "高強度" not in good

    bad = _action_text("steps", "悪化", anchors)
    assert "高強度運動を避ける" not in bad   # exercise 用の文言を使い回さない

    # exercise 側は従来どおり強度の話
    assert "高強度" in _action_text("exercise", "悪化", anchors)

"""LLM payload を組み立てるヘルパーが SQLAlchemy の DetachedInstanceError を
出さないことを保証するリグレッションテスト。

session_scope の外で attribute を参照すると DetachedInstanceError が出る。
本番で WeightSample.weight_kg を参照する箇所で実際に発火した。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.scoring.timewindow import app_today


@pytest.fixture
def app_ctx(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    from app.config import reset_settings_cache

    reset_settings_cache()
    from app.db import create_all, init_engine

    init_engine(temp_data_dir / "test.sqlite3")
    create_all()
    yield


def test_gather_caffeine_does_not_raise_detached_error(app_ctx):
    """`_gather_caffeine` は session を抜けた後でも安全に値を返す。"""
    from app.db import session_scope
    from app.llm.client import _gather_caffeine
    from app.models import WeightSample

    target = app_today()
    # 体重サンプルを 1 つ入れる
    with session_scope() as session:
        session.add(
            WeightSample(
                ts=datetime.now(UTC).replace(tzinfo=None),
                weight_kg=56.0,
                body_fat_pct=14.0,
                source="hae",
            )
        )

    # session の外で呼ばれるパターン
    out = _gather_caffeine(target)
    # session_scope の外で属性アクセスをしてもエラーが出ないこと
    assert isinstance(out, dict)
    assert "available" in out


def test_gather_caffeine_without_weight_falls_back_to_target(app_ctx):
    """体重サンプルが無くても DetachedInstanceError は出ない (config の target を使う)。"""
    from app.llm.client import _gather_caffeine

    target = app_today()
    out = _gather_caffeine(target)
    assert isinstance(out, dict)
    # 体重ゼロでなければ available=True、無ければ False。どちらでも例外は出ない
    assert "available" in out


def test_gather_caffeine_intakes_today_no_detached(app_ctx):
    from app.db import session_scope
    from app.llm.client import _gather_caffeine_intakes_today
    from app.models import CaffeineIntake

    target = app_today()
    with session_scope() as session:
        session.add(
            CaffeineIntake(
                ts=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
                source="canned_coffee",
                amount=1.0,
                unit="本",
                mg=100.0,
            )
        )

    out = _gather_caffeine_intakes_today(target)
    assert isinstance(out, list)
    if out:
        assert "ts_jst" in out[0]
        assert "mg" in out[0]


def test_gather_migraine_summary_no_detached(app_ctx):
    from app.db import session_scope
    from app.llm.client import _gather_migraine_summary
    from app.models import MigraineEpisode

    with session_scope() as session:
        session.add(
            MigraineEpisode(
                started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5),
                ended_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5, hours=-2),
                severity=6,
            )
        )

    out = _gather_migraine_summary(app_today())
    assert "count_30d" in out


def test_gather_physio_excludes_stale_readiness(app_ctx):
    """前日の Training Readiness を当日 payload に入れない (stale 回帰)。

    前日値 76 が「高負荷許容」の根拠として LLM に渡り、実際の朝 (BB 低) と
    矛盾した助言を生んだ実例があるため、当日分のみ採用する。
    """
    from app.db import session_scope
    from app.llm.client import _gather_physio
    from app.models import MetricSample
    from app.scoring.timewindow import jst_day_bounds

    target = app_today()
    start, _ = jst_day_bounds(target)
    with session_scope() as session:
        session.add(MetricSample(source="garmin", metric_key="training_readiness",
                                 ts=start - timedelta(hours=5), value=76.0, unit="score"))

    out = _gather_physio(target)
    assert "training_readiness" not in out

    # 当日分があれば採用される
    with session_scope() as session:
        session.add(MetricSample(source="garmin", metric_key="training_readiness",
                                 ts=start + timedelta(hours=7), value=42.0, unit="score"))
    out2 = _gather_physio(target)
    assert out2["training_readiness"]["score"] == 42.0

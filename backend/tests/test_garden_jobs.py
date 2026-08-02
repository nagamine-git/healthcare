from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.health import Base, GardenDaily, GoodActionLog


async def test_garden_recompute_job_runs(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        # ジョブは別スレッドで走る (app/jobs.py:blocking_job)。:memory: は接続ごとに
        # 別DBなので、既定の SingletonThreadPool だと別スレッドが空のDBを掴む。
        # StaticPool で1接続を共有し、本番 (ファイルDB) と同じ見え方にする。
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sess = Session(engine)
    sess.add(GoodActionLog(ts=datetime(2026, 6, 25, 1, 0), kind="meditation", source="manual"))
    sess.commit()

    import app.scoring.garden.jobs as jobs

    @contextmanager
    def fake_scope():
        yield sess

    monkeypatch.setattr(jobs, "session_scope", fake_scope)
    monkeypatch.setattr(jobs, "app_today", lambda: date(2026, 6, 25))

    out = await jobs.garden_recompute_job()
    assert out["status"] == "ok"
    assert sess.get(GardenDaily, date(2026, 6, 25)) is not None

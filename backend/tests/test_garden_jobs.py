from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.health import Base, GardenDaily, GoodActionLog


async def test_garden_recompute_job_runs(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
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

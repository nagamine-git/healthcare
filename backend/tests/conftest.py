from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Ensure tests never accidentally read real .env or hit real services.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("HAE_INGEST_TOKEN", "test-hae-token")
os.environ.setdefault("APP_LOG_LEVEL", "WARNING")


@pytest.fixture
def temp_data_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def db_engine(temp_data_dir: Path):
    """Engine bound to a fresh on-disk SQLite per test (WAL works on disk only)."""
    from app.db import create_all, init_engine

    engine = init_engine(temp_data_dir / "test.sqlite3")
    create_all()
    yield engine
    engine.dispose()


@pytest.fixture
def session(db_engine):
    from app.db import get_session_factory

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()

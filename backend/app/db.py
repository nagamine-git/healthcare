from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(db_path: Path | str) -> Engine:
    """Initialise (or replace) the global engine and session factory."""
    global _engine, _SessionLocal

    url = _build_url(db_path)
    engine = create_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    # 低速クエリ計測リスナーを付ける(常駐パフォーマンス監視)。
    try:
        from app.perf import attach_query_timing

        attach_query_timing(engine)
    except Exception:  # 監視は失敗してもアプリを止めない
        pass
    return engine


def _build_url(db_path: Path | str) -> str:
    if str(db_path) == ":memory:":
        return "sqlite:///:memory:"
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{p.as_posix()}"


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Engine not initialised. Call init_engine() first.")
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        raise RuntimeError("Session factory not initialised. Call init_engine() first.")
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Create all tables registered on Base.metadata."""
    # Import models to register them with Base.metadata
    from app import models  # noqa: F401

    Base.metadata.create_all(get_engine())
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """既存 DB に欠損しているカラムを ALTER で足す簡易 migration。

    Alembic を入れるほどでもないシングルユーザーアプリ向け。
    nullable で default のあるカラム追加だけ対応。
    """
    from sqlalchemy import inspect, text

    engine = get_engine()
    inspector = inspect(engine)
    expected = {
        "daily_score": [("body_fat_sub", "REAL")],
        "llm_comment": [("payload", "JSON")],
        "subjective_checkin": [("from_suggested", "JSON")],
        "learning_section_progress": [
            ("read_at", "DATETIME"),
            ("rustlings_at", "DATETIME"),
            ("explained_at", "DATETIME"),
        ],
        "learning_chapter_progress": [
            ("quiz_points", "INTEGER"),
            ("free_word_passed_at", "DATETIME"),
        ],
        "finance_state": [
            ("reserve_months", "INTEGER DEFAULT 6"),
            ("risk_tolerance", "INTEGER DEFAULT 3"),
        ],
        "asset_holding": [("risk_tier", "INTEGER")],
        "user_profile": [
            ("birth_date", "DATE"),
            ("age", "INTEGER"),
            ("resting_hr", "INTEGER"),
            ("max_hr", "INTEGER"),
            ("caffeine_smoker", "BOOLEAN"),
            ("caffeine_oral_contraceptives", "BOOLEAN"),
            ("caffeine_pregnant", "BOOLEAN"),
            ("caffeine_sensitivity", "VARCHAR(8)"),
            ("caffeine_half_life_override_h", "REAL"),
            ("wake_time", "VARCHAR(5)"),
            ("sleep_need_min", "INTEGER"),
            ("chronotype", "VARCHAR(12)"),
            ("protein_g_per_kg", "REAL"),
            ("water_ml_per_kg", "REAL"),
        ],
    }
    with engine.begin() as conn:
        for table, cols in expected.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, sql_type in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
        # 旧 done_at (節の単一トグル) を read_at へ引き継ぐ。done_at がまだ
        # 物理的に残っている既存 DB のみ対象 (新規 DB には存在しない)。
        if "learning_section_progress" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("learning_section_progress")}
            if "done_at" in cols:
                conn.execute(text(
                    "UPDATE learning_section_progress SET read_at = done_at "
                    "WHERE read_at IS NULL AND done_at IS NOT NULL"
                ))

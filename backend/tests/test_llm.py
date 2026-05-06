from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import DailyScore, LlmComment


@pytest.fixture(autouse=True)
def _settings(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app.config import reset_settings_cache
    from app.db import create_all, init_engine

    reset_settings_cache()
    init_engine(temp_data_dir / "test.sqlite3")
    create_all()


def _seed_score(d: date) -> None:
    from app.db import session_scope

    with session_scope() as session:
        session.add(
            DailyScore(
                date=d,
                sleep_sub=85,
                hrv_sub=60,
                bb_sub=70,
                load_sub=75,
                weight_sub=80,
                total=75.0,
                version="v1",
                computed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )


@pytest.mark.asyncio
async def test_generate_advice_success(monkeypatch):
    target = date(2026, 5, 1)
    _seed_score(target)

    mock_call = AsyncMock(return_value="本日は積極的にトレーニング。根拠: 総合 75 でベースライン並み。")
    monkeypatch.setattr("app.llm.client._call_anthropic", mock_call)

    from app.llm.client import generate_advice_for_date

    result = await generate_advice_for_date(target)
    assert result["status"] == "ok"
    assert result["comment"].startswith("本日")
    assert mock_call.await_count == 1

    from app.db import session_scope

    with session_scope() as session:
        stored = session.execute(select(LlmComment)).scalars().all()
        assert len(stored) == 1
        assert stored[0].comment == result["comment"]


@pytest.mark.asyncio
async def test_generate_advice_falls_back_on_exception(monkeypatch):
    target = date(2026, 5, 1)
    _seed_score(target)

    async def boom(**kwargs):
        raise RuntimeError("anthropic timeout")

    monkeypatch.setattr("app.llm.client._call_anthropic", boom)

    from app.llm.client import generate_advice_for_date

    result = await generate_advice_for_date(target)
    assert result["status"] == "fallback"
    assert "error" in result

    from app.db import session_scope

    with session_scope() as session:
        stored = session.execute(select(LlmComment)).scalars().all()
        assert len(stored) == 1
        assert stored[0].model == "fallback"


@pytest.mark.asyncio
async def test_generate_advice_uses_fallback_when_no_api_key(monkeypatch, temp_data_dir):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.config import reset_settings_cache

    reset_settings_cache()

    target = date(2026, 5, 1)
    _seed_score(target)

    from app.llm.client import generate_advice_for_date

    result = await generate_advice_for_date(target)
    assert result["status"] == "fallback"


@pytest.mark.asyncio
async def test_generate_advice_rate_limited_after_three(monkeypatch):
    target = date(2026, 5, 1)
    _seed_score(target)

    mock_call = AsyncMock(return_value="comment")
    monkeypatch.setattr("app.llm.client._call_anthropic", mock_call)

    from app.llm.client import generate_advice_for_date

    for _ in range(3):
        await generate_advice_for_date(target)
    fourth = await generate_advice_for_date(target)
    assert fourth["status"] == "rate_limited"


@pytest.mark.asyncio
async def test_generate_advice_force_overrides_rate_limit(monkeypatch):
    target = date(2026, 5, 1)
    _seed_score(target)

    mock_call = AsyncMock(return_value="comment")
    monkeypatch.setattr("app.llm.client._call_anthropic", mock_call)

    from app.llm.client import generate_advice_for_date

    for _ in range(3):
        await generate_advice_for_date(target)
    forced = await generate_advice_for_date(target, force=True)
    assert forced["status"] == "ok"


def test_build_messages_includes_cache_control():
    from app.llm.prompts import build_messages

    system, messages = build_messages(
        target=date(2026, 5, 1),
        today_payload={"score": {"total": 75}},
        baselines={"avg_total_score_28d": 72.0},
    )
    assert any(b.get("cache_control") for b in system)
    assert messages[0]["role"] == "user"

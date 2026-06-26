from __future__ import annotations

from datetime import date, datetime

from app.config import get_settings
from app.models.health import (
    GardenConfig,
    GardenDaily,
    GithubContributionDaily,
    GoodActionLog,
)


def test_garden_tables_have_expected_columns():
    assert GoodActionLog.__tablename__ == "good_action_log"
    assert GardenDaily.__tablename__ == "garden_daily"
    assert GithubContributionDaily.__tablename__ == "github_contribution_daily"
    assert GardenConfig.__tablename__ == "garden_config"
    # 列の存在確認(コンストラクタが通ること)
    GoodActionLog(ts=datetime(2026, 6, 25), kind="meditation", source="manual", value=1.0)
    GardenDaily(date=date(2026, 6, 25), intensity=0.0, level=0, contributions={}, streak_len=0)
    GithubContributionDaily(date=date(2026, 6, 25), commit_count=3)
    GardenConfig(id=1, github_username="octocat", github_token="x")


def test_garden_config_defaults_present():
    s = get_settings()
    kinds = {c["kind"] for c in s.garden_catalog}
    assert {"coding", "aerobic", "strength", "sleep", "reading", "meditation", "social"} <= kinds
    assert s.garden_gap_gamma >= 0
    assert len(s.garden_level_thresholds) == 4
    for c in s.garden_catalog:
        assert {"kind", "source", "dimensions", "base", "evidence"} <= set(c)

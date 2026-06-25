"""Compass の次元カタログと config 理想プロファイルの整合テスト。"""

from __future__ import annotations

from app.config import get_settings
from app.scoring.identity import dimensions as dim


def test_catalog_has_two_layers_and_unique_ids() -> None:
    assert len(dim.DIMENSIONS) == len(dim.BY_ID), "id に重複がある"
    assert set(dim.VALUE_IDS).isdisjoint(dim.MINDSET_IDS)
    assert len(dim.VALUE_IDS) == 10  # Schwartz 基本価値 10
    assert len(dim.MINDSET_IDS) == 7  # 起業家認知 7 次元
    for d in dim.DIMENSIONS:
        assert d.layer in ("values", "mindset")
        assert d.name_ja and d.description and d.research_basis


def test_config_archetype_covers_all_dimensions() -> None:
    s = get_settings()
    targets = s.identity_archetype_targets
    weights = s.identity_archetype_weights
    # 理想プロファイルはカタログ全次元を過不足なく覆う。
    assert set(targets) == set(dim.ALL_IDS)
    assert set(weights) == set(dim.ALL_IDS)
    for v in targets.values():
        assert 0 <= v <= 100
    for w in weights.values():
        assert w > 0


def test_founder_archetype_favors_mindset() -> None:
    s = get_settings()
    targets = s.identity_archetype_targets
    # 脱サラリーマンマインドの方向: マインドセット層は高く、保守系価値は低い。
    assert targets["ownership"] >= 85
    assert targets["proactivity"] >= 85
    assert targets["conformity"] <= 40
    assert targets["tradition"] <= 40

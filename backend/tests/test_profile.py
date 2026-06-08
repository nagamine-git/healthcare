from __future__ import annotations

from app.db import session_scope
from app.models import UserProfile


def test_resolve_falls_back_to_settings(db_engine):
    from app.scoring.profile import resolve_profile

    p = resolve_profile()
    # DB 行が無ければ settings のデフォルト (例プロファイル: 65/18) が出る
    assert p.source == "default"
    assert p.target_weight_kg == 65.0
    assert p.target_body_fat_pct == 18.0
    assert p.height_cm == 170.0


def test_resolve_uses_db_row(db_engine):
    from app.scoring.profile import resolve_profile

    with session_scope() as s:
        s.add(UserProfile(id=1, height_cm=165.0, sex="male",
                          target_weight_kg=55.0, target_body_fat_pct=15.0,
                          body_fat_tolerance_pct=1.5, ffmi_normalized=18.0))

    p = resolve_profile()
    assert p.source == "db"
    assert p.height_cm == 165.0
    assert p.target_weight_kg == 55.0
    assert p.target_body_fat_pct == 15.0


def test_resolve_partial_null_falls_back_per_field(db_engine):
    from app.scoring.profile import resolve_profile

    with session_scope() as s:
        # 体重だけ設定、他は NULL → 他は settings デフォルト
        s.add(UserProfile(id=1, target_weight_kg=55.0))

    p = resolve_profile()
    assert p.source == "db"
    assert p.target_weight_kg == 55.0
    assert p.target_body_fat_pct == 18.0  # settings default
    assert p.height_cm == 170.0  # settings default

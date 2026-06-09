from __future__ import annotations

from app.scoring.timewindow import app_today


def test_sodium_target_is_sodium_mg_not_salt_equivalent(session):
    """食塩相当量 7.5g を 7500mg と混同しない (Na mg = 食塩g × 393 ≒ 2950)。"""
    from app.scoring.nutrition import aggregate_nutrition

    out = aggregate_nutrition(session, app_today())
    t = out["targets"]["sodium_mg"]
    assert t["ideal"] == 2000.0  # WHO 推奨 (ナトリウム mg)
    assert t["max"] == 2950.0  # 日本人男性 DG 食塩 7.5g のナトリウム換算
    assert t["unit"] == "mg"

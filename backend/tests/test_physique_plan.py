from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.scoring.physique_plan import (
    _eta_label,
    _kcal_per_min_shadowbox,
    _levers,
    _macros,
    _muscle_rate_pct_month,
    _weeks_to_gain_lean,
)

# ----- 純粋な数理 -----


def test_macros_protein_from_per_kg():
    m = _macros(2000, 80, 2.0)
    assert m["protein_g"] == 160  # 2.0 * 80
    assert m["protein_kcal"] == 640


def test_macros_carbs_never_negative():
    # 極端に低いカロリーでも炭水化物は負にならない
    m = _macros(500, 80, 2.0)
    assert m["carb_g"] >= 0
    assert m["fat_g"] >= 0


def test_shadowbox_kcal_per_min_positive_scales_with_weight():
    assert _kcal_per_min_shadowbox(60) < _kcal_per_min_shadowbox(90)


@pytest.mark.parametrize("direction", ["cut", "recomp", "lean_bulk", "maintain"])
def test_levers_sum_to_100(direction):
    levers = _levers(direction, 160, 45)
    assert sum(x["share_pct"] for x in levers) == 100


def test_eta_label_done():
    assert "到達" in _eta_label(0)
    assert "週" in _eta_label(4)
    assert "ヶ月" in _eta_label(20)


def test_muscle_rate_higher_when_ffmi_low():
    # FFMI が低い(伸びしろ大) ほど速い。天井近くは遅い。
    low = _muscle_rate_pct_month(16.0, "male")
    high = _muscle_rate_pct_month(24.0, "male")
    assert low > high
    assert low == pytest.approx(1.0)  # baseline 以下は rate_max にクランプ
    assert high < 0.2  # 天井近くは僅か


def test_weeks_to_gain_decelerates():
    # 同じ +6kg でも、開始 FFMI が高い方が(天井に近く)時間がかかる
    fast = _weeks_to_gain_lean(45.0, 51.0, 54.0, 170, "male")  # FFMI ~低
    slow = _weeks_to_gain_lean(63.0, 69.0, 78.0, 170, "male")  # FFMI ~高
    assert 0 < fast < slow


# ----- API 統合 (実データ経路) -----


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_physique_plan_recomp_direction(app_client):
    from app.db import session_scope
    from app.models import UserProfile, WeightSample

    with session_scope() as s:
        s.add(WeightSample(
            ts=datetime.now(UTC).replace(tzinfo=None),
            weight_kg=85.0, body_fat_pct=24.0, source="test",
        ))
        # 同体重で組成だけ入れ替え (85kg維持・体脂肪24%→15%) → recomp
        s.merge(UserProfile(
            id=1, height_cm=175.0, sex="male",
            target_weight_kg=85.0, target_body_fat_pct=15.0, age=35,
        ))

    r = app_client.get("/api/physique-plan").json()
    assert r["available"] is True
    # 同体重で脂肪減 + 筋増 → recomp
    assert r["direction"] == "recomp"
    assert r["gap"]["d_fat_mass_kg"] < 0  # 脂肪を減らす
    # 緩い赤字方向 → カロリー目標 < TDEE
    assert r["energy"]["calorie_target"] < r["energy"]["tdee"]
    assert r["energy"]["tdee_measured"] is False  # DailySummary 無し → 推定
    # タンパク質は per kg から (既定 2.0 * 85 = 170)
    assert r["macros"]["protein_g"] == 170
    # 食事 vs 運動: 赤字を運動で作る分数が出る
    assert r["diet_vs_exercise"]["shadowbox_min_equiv"] > 0
    assert sum(x["share_pct"] for x in r["levers"]) == 100
    assert r["timeline"]["eta_weeks"] > 0


def test_physique_plan_lean_bulk_needs_surplus(app_client):
    """純増目標 (体重を増やす) は維持では到達不能 → 黒字 (lean_bulk)。"""
    from app.db import session_scope
    from app.models import UserProfile, WeightSample

    with session_scope() as s:
        s.add(WeightSample(
            ts=datetime.now(UTC).replace(tzinfo=None),
            weight_kg=54.0, body_fat_pct=16.0, source="test",
        ))
        s.merge(UserProfile(
            id=1, height_cm=170.0, sex="male",
            target_weight_kg=59.0, target_body_fat_pct=12.0, age=35,
        ))

    r = app_client.get("/api/physique-plan").json()
    assert r["direction"] == "lean_bulk"
    # 純増 → 黒字 (カロリー目標 > TDEE)
    assert r["energy"]["calorie_target"] > r["energy"]["tdee"]
    assert r["energy"]["delta_kcal"] > 0
    assert "黒字" in r["diet_vs_exercise"]["headline"]
    # 12週ブロックと今日の具体行動が出る
    assert r["block"] is not None
    assert r["block"]["expected_lean_kg"] > 0
    assert 0 < r["block"]["pct_of_goal"] <= 100
    keys = {a["key"] for a in r["today_actions"]}
    assert {"protein", "calorie", "training"} <= keys


def test_physique_plan_no_weight(app_client):
    r = app_client.get("/api/physique-plan").json()
    assert r["available"] is False

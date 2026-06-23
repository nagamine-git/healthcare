from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.scoring.meal_estimate import estimate_usual_macros, meal_suggestions


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


def _add_food(client, name, kcal, protein, **kw):
    r = client.post("/api/foods", json={"name": name, "kcal": kcal, "protein_g": protein, **kw})
    assert r.status_code == 200
    return r.json()


def test_food_crud(app_client):
    f = _add_food(app_client, "ゆで卵", 68, 6.0, is_protein_source=True, unit_label="1個")
    assert f["id"] > 0
    items = app_client.get("/api/foods").json()["items"]
    assert any(i["name"] == "ゆで卵" for i in items)
    # 更新
    app_client.put(f"/api/foods/{f['id']}", json={"name": "ゆで卵L", "kcal": 80, "protein_g": 7.0})
    assert app_client.get("/api/foods").json()["items"][0]["name"] == "ゆで卵L"
    # 削除
    app_client.delete(f"/api/foods/{f['id']}")
    assert app_client.get("/api/foods").json()["items"] == []


def test_estimate_endpoint_mocked(app_client, monkeypatch):
    # LLM をモックして food→マクロ推定をネットワーク非依存に
    async def fake(name, qty_text):
        return {"name": name, "kcal": 200.0, "protein_g": 20.0, "fat_g": 8.0,
                "carb_g": 12.0, "unit_label": "1本", "category": "タンパク源", "is_protein_source": True}
    monkeypatch.setattr("app.llm.food.estimate_food_macros", fake)
    r = app_client.post("/api/foods/estimate", json={"name": "プロテインバー", "qty_text": "1本"}).json()
    assert r["available"] is True
    assert r["protein_g"] == 20.0
    assert r["is_protein_source"] is True


def test_meal_pattern_estimation(app_client):
    egg = _add_food(app_client, "ゆで卵", 68, 6.0, is_protein_source=True, unit_label="1個")
    bread = _add_food(app_client, "菓子パン", 300, 5.0, category="間食", unit_label="1個")
    # 朝: ゆで卵2個(毎日)、間食: 菓子パン(よく)
    app_client.post("/api/meal-patterns", json={"slot": "breakfast", "food_id": egg["id"], "qty": 2, "frequency": "daily"})
    app_client.post("/api/meal-patterns", json={"slot": "snack", "food_id": bread["id"], "qty": 1, "frequency": "often"})
    plan = app_client.get("/api/meal-plan").json()
    # 記録が無いのでパターン推定が使われる
    assert plan["usual"]["source"] == "pattern"
    # 卵2個(12g) + 菓子パン0.6回(3g) ≈ 15g 前後
    assert plan["usual"]["estimate"]["protein_g"] == pytest.approx(15.0, abs=1.0)


def test_breakfast_only_fixed_rest_variable(app_client):
    """朝だけ固定登録 → 昼夜はランダム扱い、残りの必要量を案内する。"""
    egg = _add_food(app_client, "ゆで卵", 68, 6.0, is_protein_source=True, unit_label="1個")
    app_client.post("/api/meal-patterns", json={"slot": "breakfast", "food_id": egg["id"], "qty": 2, "frequency": "daily"})
    plan = app_client.get("/api/meal-plan").json()
    u = plan["usual"]
    assert u["source"] == "pattern"
    assert u["complete"] is False  # 昼夜が未登録
    assert "lunch" in u["variable_slots"] and "dinner" in u["variable_slots"]
    assert u["fixed_protein_g"] == pytest.approx(12.0, abs=0.5)  # 卵2個
    # 固定18gを全日扱いせず、残りをランダム枠で確保する案内
    kinds = {s["kind"] for s in plan["suggestions"]}
    assert "variable_target" in kinds
    txt = next(s["text"] for s in plan["suggestions"] if s["kind"] == "variable_target")
    assert "残り" in txt and "1食あたり" in txt


def test_meal_suggestions_recommends_protein(app_client):
    _add_food(app_client, "プロテイン", 120, 24.0, is_protein_source=True, unit_label="1杯")
    plan = app_client.get("/api/meal-plan").json()
    # タンパク質目標に対し不足 → 追加サジェストが出る
    kinds = {s["kind"] for s in plan["suggestions"]}
    assert "add" in kinds or "info" in kinds or "ok" in kinds


def test_usual_from_logged_history_and_decomposition(app_client):
    """Apple Health の実キー(protein/dietary_energy)から過去の実績を推定し、
    固定(朝)を引いた残り(昼夜間食)を分解する。"""
    from datetime import UTC, datetime, timedelta

    from app.db import session_scope
    from app.models import MealPattern, MetricSample

    egg = _add_food(app_client, "ゆで卵", 68, 6.0, is_protein_source=True, unit_label="1個")
    with session_scope() as s:
        # 朝固定: 卵2個(12g)
        s.add(MealPattern(slot="breakfast", food_id=egg["id"], qty=2, frequency="daily"))
        # 過去の食事記録 (実キー): 1日 protein 60g / energy 1800kcal を数日分
        for d in range(1, 6):
            ts = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=d * 5)
            s.add(MetricSample(ts=ts, metric_key="protein", value=60.0, source="test"))
            s.add(MetricSample(ts=ts, metric_key="dietary_energy", value=1800.0, source="test"))
    plan = app_client.get("/api/meal-plan").json()
    u = plan["usual"]
    assert u["source"] == "logged"  # 記録ベース
    assert u["estimate"]["protein_g"] == pytest.approx(60.0, abs=1.0)
    assert u["logged_days"] == 5
    # 実績60 − 固定12 = 残り(昼夜間食)~48g
    assert u["inferred_variable"]["protein_g"] == pytest.approx(48.0, abs=1.0)
    # 「過去の実績」サジェストが出る
    assert any(sg["kind"] == "usual" for sg in plan["suggestions"])


def test_estimate_usual_none_when_empty(db_engine):
    from datetime import date

    out = estimate_usual_macros(date(2026, 6, 16))
    assert out["source"] == "none"
    assert out["estimate"] is None


def test_meal_suggestions_setup_when_no_foods(db_engine):
    from datetime import date

    out = meal_suggestions(date(2026, 6, 16))
    assert any(s["kind"] == "setup" for s in out["suggestions"])

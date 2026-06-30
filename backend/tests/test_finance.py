from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import session_scope
from app.models.health import AssetHolding, RoiCandidate
from app.scoring.finance import compute_finance, get_state


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_rebalance_reserve_and_room(db_engine):
    with session_scope() as session:
        get_state(session).reserve_jpy = 1_000_000
        session.add(AssetHolding(name="現金", category="cash", value_jpy=1_500_000, target_weight=0))
        session.add(AssetHolding(name="仮想通貨", category="crypto", value_jpy=300_000, target_weight=1))
        session.add(AssetHolding(name="積立", category="invest", value_jpy=200_000, target_weight=1))
    with session_scope() as session:
        f = compute_finance(session)
    reb = f["rebalance"]
    # 総資産200万、防衛資金100万 → 余剰100万
    assert reb["total"] == 2_000_000 and reb["reserve"] == 1_000_000 and reb["investable"] == 1_000_000
    crypto = next(h for h in reb["holdings"] if h["name"] == "仮想通貨")
    # 目標 = 余剰100万 × (1/2) = 50万 → あと20万買える
    assert crypto["target_value"] == 500_000
    assert crypto["room"] == 200_000 and crypto["signal"] == "buy"


def test_roi_ranking_and_verdict(db_engine):
    with session_scope() as session:
        get_state(session).wage_jpy_per_h = 2000
        # 月5h削減・毎日使う買い切り1万 → ROI高
        session.add(RoiCandidate(name="高ROIツール", cost_jpy=12_000, period="onetime",
                                 monthly_use_days=30, monthly_time_saved_h=5, status="considering"))
        # ほぼ使わない高額サブスク → 低ROI
        session.add(RoiCandidate(name="低ROIサブスク", cost_jpy=3_000, period="month",
                                 monthly_use_days=1, monthly_time_saved_h=0, status="owning"))
    with session_scope() as session:
        f = compute_finance(session)
    roi = f["roi"]["candidates"]
    assert roi[0]["name"] == "高ROIツール" and roi[0]["score"] > roi[1]["score"]
    low = next(r for r in roi if r["name"] == "低ROIサブスク")
    assert low["verdict"] == "cancel"  # 保有中×低スコア → 解約候補


def test_import_cashflow_sets_reserve_from_monthly_expense(app_client):
    # 計算対象=1 & 振替=0 の支出だけを集計。3ヶ月で各10万支出 → 月平均10万 → 防衛資金=10万×6。
    header = "計算対象,日付,内容,金額（円）,保有金融機関,大項目,中項目,メモ,振替,ID\n"
    rows = [
        "1,2026/03/15,家賃,-100000,UFJ,住宅,家賃,,0,t1",
        "1,2026/04/15,家賃,-100000,UFJ,住宅,家賃,,0,t2",
        "1,2026/05/15,家賃,-100000,UFJ,住宅,家賃,,0,t3",
        "1,2026/04/25,給与,300000,UFJ,収入,給与,,0,i1",
        "0,2026/04/01,振替,-50000,UFJ,未分類,未分類,,1,x1",  # 振替/対象外は除外
    ]
    r = app_client.post("/api/finance/import-cashflow", json={"csv": header + "\n".join(rows)})
    assert r.status_code == 200
    cf = r.json()["cashflow"]
    assert cf["has_data"] and cf["avg_monthly_expense"] == 100000
    assert r.json()["rebalance"]["reserve"] == 600000  # 月10万 × 6ヶ月(自動設定)
    # 再アップロードで重複しない
    r2 = app_client.post("/api/finance/import-cashflow", json={"csv": header + "\n".join(rows)})
    assert r2.json()["cashflow"]["tx_count"] == 4  # counted & not transfer のみ


def test_import_assets_csv_upserts(app_client):
    csv = "現金,1500000\n仮想通貨,¥300,000\n"
    r = app_client.post("/api/finance/import-assets", json={"csv": csv})
    assert r.status_code == 200
    names = {h["name"] for h in r.json()["rebalance"]["holdings"]}
    assert {"現金", "仮想通貨"} <= names

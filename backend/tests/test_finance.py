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
    # 総資産200万、防衛資金100万 → 余剰100万(情報)。目標額は総資産ベース。
    assert reb["total"] == 2_000_000 and reb["reserve"] == 1_000_000 and reb["investable"] == 1_000_000
    crypto = next(h for h in reb["holdings"] if h["name"] == "仮想通貨")
    # 目標 = 総資産200万 × (1/2) = 100万 → あと70万買える
    assert crypto["target_value"] == 1_000_000
    assert crypto["room"] == 700_000 and crypto["signal"] == "buy"


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
    assert roi[0]["monthly_use_days"] == 30  # 編集フォーム復元用に活用日も返す
    low = next(r for r in roi if r["name"] == "低ROIサブスク")
    assert low["verdict"] == "cancel"  # 保有中×低スコア → 解約候補


def test_get_state_tolerates_null_columns(db_engine):
    # 旧DBで後付け列が NULL の行でも compute_finance が落ちない(get_state が補正)。
    from app.models.health import FinanceState

    with session_scope() as session:
        session.add(FinanceState(id=1, reserve_jpy=None, reserve_months=None, wage_jpy_per_h=None))
    with session_scope() as session:
        st = get_state(session)
        assert st.reserve_months == 6 and st.wage_jpy_per_h == 2000.0
        f = compute_finance(session)  # 例外を出さない
        assert "rebalance" in f


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


def test_auto_allocate_recursive_risk_split(app_client):
    from app.scoring.finance import classify_risk_tier

    assert classify_risk_tier("三菱UFJ銀行 普通") == 0
    assert classify_risk_tier("SBI証券 eMAXIS Slim 全世界株式") == 2
    assert classify_risk_tier("Coincheck ビットコイン残高") == 3
    assert classify_risk_tier("bitFlyer ベーシックアテンショントークン残高") == 4

    for n, v in [("UFJ 普通", 700000), ("NISA 全世界株式", 200000),
                 ("Coincheck ビットコイン残高", 100000)]:
        app_client.post("/api/finance/asset", json={"name": n, "value_jpy": v})
    r = app_client.post("/api/finance/auto-allocate", json={"tolerance": 3})  # safe 0.70
    assert r.status_code == 200
    w = {h["name"]: h["target_weight"] for h in r.json()["rebalance"]["holdings"]}
    # 生比率 現金0.7 : 株0.21 : 暗号0.063 を正規化(合計100)。
    assert round(w["UFJ 普通"]) == 72           # 現金
    assert round(w["NISA 全世界株式"]) == 22     # 株
    assert round(w["Coincheck ビットコイン残高"]) == 6   # 主要暗号(残余を丸取りしない)
    assert r.json()["rebalance"]["risk_tolerance"] == 3


def test_import_assets_csv_upserts(app_client):
    csv = "現金,1500000\n仮想通貨,¥300,000\n"
    r = app_client.post("/api/finance/import-assets", json={"csv": csv})
    assert r.status_code == 200
    names = {h["name"] for h in r.json()["rebalance"]["holdings"]}
    assert {"現金", "仮想通貨"} <= names


def test_merge_asset_items_same_name_different_value_kept_separately():
    """同一銘柄が複数口座 (特定/NISA 等) にある場合は潰さず連番サフィックスで別行に。"""
    from app.api.finance import merge_asset_items

    items = [
        {"name": "SBI証券 eMAXIS Slim 米国株式(S&P500)", "value": 423410.0},
        {"name": "SBI証券 eMAXIS Slim 米国株式(S&P500)", "value": 180000.0},
    ]
    merged = merge_asset_items(items)
    assert len(merged) == 2
    assert merged[0]["name"] == "SBI証券 eMAXIS Slim 米国株式(S&P500)"
    assert merged[1]["name"] == "SBI証券 eMAXIS Slim 米国株式(S&P500) (2)"
    assert merged[1]["value"] == 180000.0


def test_merge_asset_items_screenshot_overlap_deduped():
    """複数スクショの重なりで同じ行 (銘柄+金額が完全一致) が2回写ったら1つに。"""
    from app.api.finance import merge_asset_items

    items = [
        {"name": "三菱UFJ銀行 普通", "value": 719540.0},
        {"name": "三菱UFJ銀行 普通", "value": 719540.0},  # 画面の重なり
        {"name": "みずほ銀行 普通", "value": 190167.0},
    ]
    merged = merge_asset_items(items)
    assert len(merged) == 2
    assert [m["name"] for m in merged] == ["三菱UFJ銀行 普通", "みずほ銀行 普通"]


def test_merge_asset_items_three_way_split_numbered():
    from app.api.finance import merge_asset_items

    items = [
        {"name": "X", "value": 1.0},
        {"name": "X", "value": 2.0},
        {"name": "X", "value": 3.0},
        {"name": "X", "value": 2.0},  # 2 とは重なり (同値) → 排除
    ]
    merged = merge_asset_items(items)
    assert [(m["name"], m["value"]) for m in merged] == [
        ("X", 1.0), ("X (2)", 2.0), ("X (3)", 3.0),
    ]


def test_import_assets_same_name_two_accounts_end_to_end(app_client):
    """eMAXIS が2口座 → 上書きで1つに潰れず、2行とも保存される (実バグ再現)。"""
    csv = (
        "SBI証券 eMAXIS Slim 米国株式(S&P500),423410\n"
        "SBI証券 eMAXIS Slim 米国株式(S&P500),180000\n"
    )
    r = app_client.post("/api/finance/import-assets", json={"csv": csv})
    assert r.status_code == 200
    holdings = r.json()["rebalance"]["holdings"]
    emaxis = [h for h in holdings if "eMAXIS" in h["name"]]
    assert len(emaxis) == 2
    assert sorted(h["value_jpy"] for h in emaxis) == [180000.0, 423410.0]


def test_import_assets_replace_wipes_stale_import_rows(app_client):
    """スクショ取込は「その取込を正」として、写っていない import 行を一掃する。"""
    r1 = app_client.post("/api/finance/import-assets", json={"csv": "旧資産A,100\n旧資産B,200\n"})
    assert r1.status_code == 200
    r2 = app_client.post("/api/finance/import-assets", json={"csv": "旧資産A,150\n新資産C,300\n"})
    names = {h["name"]: h for h in r2.json()["rebalance"]["holdings"]}
    assert "旧資産B" not in names          # 写っていない → 削除
    assert names["旧資産A"]["value_jpy"] == 150.0  # 一致 → 値更新
    assert names["新資産C"]["value_jpy"] == 300.0


def test_import_assets_replace_preserves_target_weight(app_client):
    """一致した行の目標ウェイト (ユーザー設定) は取込で消えない。"""
    app_client.post("/api/finance/import-assets", json={"csv": "eMAXIS,1000\n"})
    # ユーザーが目標ウェイトを設定
    r = app_client.get("/api/finance")
    h = next(x for x in r.json()["rebalance"]["holdings"] if x["name"] == "eMAXIS")
    app_client.post("/api/finance/asset", json={
        "id": h["id"], "name": "eMAXIS", "category": "import",
        "value_jpy": 1000, "target_weight": 42.0,
    })
    # 再取込 (値だけ変わる)
    r2 = app_client.post("/api/finance/import-assets", json={"csv": "eMAXIS,1100\n"})
    h2 = next(x for x in r2.json()["rebalance"]["holdings"] if x["name"] == "eMAXIS")
    assert h2["value_jpy"] == 1100.0
    assert h2["target_weight"] == 42.0


def test_import_assets_replace_keeps_manual_rows(app_client):
    """手動追加 (category != import) の資産は一掃の対象外。"""
    app_client.post("/api/finance/asset", json={"name": "手動の金庫", "category": "cash", "value_jpy": 5000})
    r = app_client.post("/api/finance/import-assets", json={"csv": "スクショ資産,100\n"})
    names = {h["name"] for h in r.json()["rebalance"]["holdings"]}
    assert "手動の金庫" in names


def test_import_assets_replace_false_appends(app_client):
    """replace=false なら従来どおり追記 (何も消さない)。"""
    app_client.post("/api/finance/import-assets", json={"csv": "資産A,100\n"})
    r = app_client.post("/api/finance/import-assets", json={"csv": "資産B,200\n", "replace": False})
    names = {h["name"] for h in r.json()["rebalance"]["holdings"]}
    assert {"資産A", "資産B"} <= names


def test_auto_allocate_excludes_dust(app_client):
    # 総資産の1%未満の極小残高は投資対象外(target_weight=0)。実データのBAT(916円)相当。
    for n, v in [("UFJ 普通", 700000),
                 ("Coincheck ビットコイン残高", 118758),
                 ("bitFlyer ベーシックアテンショントークン残高", 916)]:
        app_client.post("/api/finance/asset", json={"name": n, "value_jpy": v})
    r = app_client.post("/api/finance/auto-allocate", json={"tolerance": 3})
    holds = {h["name"]: h for h in r.json()["rebalance"]["holdings"]}
    bat = holds["bitFlyer ベーシックアテンショントークン残高"]
    assert bat["target_weight"] == 0.0          # 端数 → 配分対象外
    assert bat["signal"] == "reserve"           # 「買え」倒錯が消える
    assert holds["Coincheck ビットコイン残高"]["target_weight"] > 0  # 主力は配分対象


def test_auto_allocate_no_alt_windfall(app_client):
    # 主要暗号(tier3)が複数銘柄で希薄化しても、単独の高ボラアルト(tier4)が上回らない。
    # 旧ロジックは最下層tierが残余を丸取りし BTC<アルト に逆転していた。
    for n, v in [("UFJ 普通", 700000),
                 ("Coincheck ビットコイン残高", 100000),
                 ("Coincheck イーサリアム残高", 200000),
                 ("bitFlyer リップル残高", 100000)]:  # XRP=tier4, 端数閾値超
        app_client.post("/api/finance/asset", json={"name": n, "value_jpy": v})
    r = app_client.post("/api/finance/auto-allocate", json={"tolerance": 3})
    w = {h["name"]: h["target_weight"] for h in r.json()["rebalance"]["holdings"]}
    assert 0 < w["bitFlyer リップル残高"] < w["Coincheck ビットコイン残高"]


# --- ROI候補 AI自動補完 (Phase 1) ---

async def test_suggest_roi_normalizes_enum_and_types(monkeypatch):
    # LLM(_suggest)が返す生値を型/enum正規化する。
    from app.llm import finance_roi_ai

    async def fake(**kwargs):
        return {
            "cost_jpy": "441800",     # 文字列 → float
            "period": "サブスク",      # enum外 → onetime(安全側)
            "monthly_use_days": 8,
            "monthly_time_saved_h": 5,
            "monthly_revenue_jpy": 1000,
            "resale_jpy": 100000,
            "url": "https://example.com/mac",
            "note": "高性能WS",
            "reasons": {"cost_jpy": "Apple公式価格", "period": "本体購入"},
        }

    monkeypatch.setattr(finance_roi_ai, "_suggest", fake)
    out = await finance_roi_ai.suggest_roi(name="mac mini Pro")
    assert out is not None
    f = out["fields"]
    assert f["cost_jpy"] == 441800.0
    assert f["period"] == "onetime"
    assert f["monthly_time_saved_h"] == 5.0
    assert f["resale_jpy"] == 100000.0
    assert f["url"] == "https://example.com/mac"
    assert out["reasons"]["cost_jpy"] == "Apple公式価格"


async def test_suggest_roi_none_without_api_key(monkeypatch):
    from app.llm import finance_roi_ai

    monkeypatch.setattr(
        finance_roi_ai, "get_settings",
        lambda: type("S", (), {"anthropic_api_key": None, "llm_model": "x"})(),
    )
    assert await finance_roi_ai.suggest_roi(name="x") is None


def test_roi_suggest_endpoint_mocked(app_client, monkeypatch):
    # エンドポイントは suggest_roi の結果をそのまま返し、DBには保存しない。
    async def fake_suggest(**kwargs):
        return {
            "fields": {"cost_jpy": 441800.0, "period": "onetime", "monthly_use_days": 8.0,
                       "monthly_time_saved_h": 5.0, "monthly_revenue_jpy": 1000.0,
                       "resale_jpy": 100000.0, "url": None, "note": "WS"},
            "reasons": {"cost_jpy": "公式価格"},
        }

    monkeypatch.setattr("app.api.finance.suggest_roi", fake_suggest)
    r = app_client.post("/api/finance/roi-suggest", json={"name": "mac mini Pro"})
    assert r.status_code == 200
    body = r.json()
    assert body["fields"]["cost_jpy"] == 441800.0
    assert body["reasons"]["cost_jpy"] == "公式価格"
    # DBには保存されない(候補は増えない)
    assert len(app_client.get("/api/finance").json()["roi"]["candidates"]) == 0


def test_roi_suggest_endpoint_returns_null_without_api_key(app_client, monkeypatch):
    # suggest_roi が None(APIキー無/失敗)なら fields=null で返す(500にしない)。
    async def none_suggest(**kwargs):
        return None

    monkeypatch.setattr("app.api.finance.suggest_roi", none_suggest)
    r = app_client.post("/api/finance/roi-suggest", json={"name": "x"})
    assert r.status_code == 200
    assert r.json()["fields"] is None


# --- Amazon wishlist 一括取込 (Phase 2) ---

async def test_extract_wishlist_normalizes(monkeypatch):
    from app.llm import finance_roi_ai

    async def fake(**kwargs):
        return {"items": [
            {"name": "Mac mini", "price_jpy": "88000", "url": "https://amazon.co.jp/x"},
            {"name": "  ", "price_jpy": 0},  # 空名 → 除外
        ]}

    monkeypatch.setattr(finance_roi_ai, "_extract_wishlist", fake)
    out = await finance_roi_ai.extract_wishlist_items(html="<html>wishlist</html>")
    assert len(out) == 1
    assert out[0]["name"] == "Mac mini"
    assert out[0]["cost_jpy"] == 88000.0
    assert out[0]["period"] == "onetime"
    assert out[0]["url"] == "https://amazon.co.jp/x"


def test_wishlist_import_endpoint_url(app_client, monkeypatch):
    async def fake_fetch(url):
        return "<html>wishlist html</html>"

    async def fake_extract(**kwargs):
        return [{"name": "Mac mini", "cost_jpy": 88000.0, "period": "onetime", "url": "https://x"}]

    monkeypatch.setattr("app.api.finance._fetch_url", fake_fetch)
    monkeypatch.setattr("app.api.finance.extract_wishlist_items", fake_extract)
    r = app_client.post("/api/finance/roi-import-wishlist", json={"url": "https://amazon.co.jp/hz/wishlist/ls/X"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["name"] == "Mac mini" and items[0]["cost_jpy"] == 88000.0
    # 取込は候補を返すだけ(DB保存しない)
    assert len(app_client.get("/api/finance").json()["roi"]["candidates"]) == 0


def test_wishlist_import_falls_back_to_image(app_client, monkeypatch):
    # url fetch 失敗(None)時は画像OCRにフォールバック。
    async def fail_fetch(url):
        return None

    seen = {}

    async def fake_extract(**kwargs):
        seen.update(kwargs)
        return [{"name": "From image", "cost_jpy": 1000.0, "period": "onetime", "url": None}]

    monkeypatch.setattr("app.api.finance._fetch_url", fail_fetch)
    monkeypatch.setattr("app.api.finance.extract_wishlist_items", fake_extract)
    r = app_client.post("/api/finance/roi-import-wishlist",
                        json={"url": "https://amazon.co.jp/x", "image_base64": "abc", "media_type": "image/png"})
    assert r.status_code == 200
    assert r.json()["items"][0]["name"] == "From image"
    assert seen.get("image_b64") == "abc"  # 画像経路が使われた


# ===== 生活状況プロフィール + 最善手アドバイザー =====


def test_compute_finance_includes_advisor(db_engine):
    from app.scoring.finance import get_life_profile

    with session_scope() as session:
        session.add(AssetHolding(name="現金", category="cash", value_jpy=3_000_000, target_weight=0))
        session.add(AssetHolding(name="積立", category="invest", value_jpy=1_000_000, target_weight=1))
        get_state(session).reserve_jpy = 1_000_000
        lp = get_life_profile(session)
        lp.debt_balance_jpy = 500_000
        lp.debt_rate_pct = 15.0  # 高利 → 悪い借金
    with session_scope() as session:
        f = compute_finance(session)
    adv = f["advisor"]
    assert adv["gross"] == 4_000_000
    assert adv["net"] == 3_500_000  # gross - debt
    assert adv["headline"] == 4_000_000 * 3_500_000
    assert adv["leverage"] == "bad"
    assert adv["moves"][0]["kind"] == "debt"  # 高利返済が最優先
    assert f["profile"]["debt_rate_pct"] == 15.0


def test_profile_put_get_roundtrip(app_client):
    r = app_client.put(
        "/api/finance/profile",
        json={"housing": "rent", "housing_cost_jpy": 120000,
              "debt_balance_jpy": 800000, "debt_rate_pct": 1.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert "advisor" in body
    assert body["profile"]["housing"] == "rent"
    assert body["advisor"]["leverage"] == "good"  # 1% は低利=良い借金
    g = app_client.get("/api/finance/profile").json()
    assert g["housing_cost_jpy"] == 120000 and g["debt_rate_pct"] == 1.0

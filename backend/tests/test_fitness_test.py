from __future__ import annotations

from datetime import date

import pytest

from app.db import session_scope
from app.models import FitnessTestResult
from app.scoring.fitness_test import (
    FITNESS_TESTS,
    build_overview,
    composite_fitness,
    compute_due,
    compute_trend,
    evaluate,
    fitness_percentile,
    grip_best,
    srt_percentile,
)

# ---- 分布 percentile / 総合点 ----

def test_fitness_percentile_at_mean_is_50():
    # grip 30-49男性 mean=47 → ちょうど50パーセンタイル
    p = fitness_percentile("grip", 47, age=38, sex="male")
    assert p == pytest.approx(50.0, abs=1.0)


def test_fitness_percentile_monotonic_and_missing():
    lo = fitness_percentile("push_up", 10, age=38, sex="male")
    hi = fitness_percentile("push_up", 40, age=38, sex="male")
    assert lo is not None and hi is not None and hi > lo
    assert fitness_percentile("grip", 47, age=None, sex="male") is None
    assert fitness_percentile("grip", 47, age=38, sex=None) is None


def test_srt_percentile_linear():
    assert srt_percentile(0) == 0
    assert srt_percentile(10) == 100
    assert srt_percentile(5) == 50
    assert srt_percentile(None) is None


def test_composite_weighted_and_renormalized():
    # 全テスト50 → 総合50
    full = composite_fitness({"grip": 50, "push_up": 50, "chair_stand": 50, "srt": 50})
    assert full["score"] == pytest.approx(50.0, abs=0.1)
    assert full["n_tests"] == 4
    # 握力だけ測定 → 重み再正規化で握力の値そのもの
    only_grip = composite_fitness({"grip": 80, "push_up": None, "chair_stand": None, "srt": None})
    assert only_grip["score"] == pytest.approx(80.0, abs=0.1)
    assert only_grip["n_tests"] == 1
    # 重み付け確認: grip(0.35)=100, push_up(0.25)=0, 他なし → 100*0.35/(0.35+0.25)=58.3
    w = composite_fitness({"grip": 100, "push_up": 0})
    assert w["score"] == pytest.approx(58.3, abs=0.2)
    # 全欠損 → None
    assert composite_fitness({"grip": None, "push_up": None}) is None


# ---- evaluate: バンド境界 ----

def test_evaluate_pushup_bands():
    # 40回以上で優、39で良
    assert evaluate("push_up", 40, age=38, sex="male")["label"] == "優"
    assert evaluate("push_up", 39, age=38, sex="male")["label"] == "良"
    assert evaluate("push_up", 9, age=38, sex="male")["label"] == "要改善"


def test_evaluate_grip_bands():
    assert evaluate("grip", 47, age=38, sex="male")["label"] == "良"
    assert evaluate("grip", 46, age=38, sex="male")["label"] == "平均"
    assert evaluate("grip", 52, age=38, sex="male")["label"] == "優"


def test_evaluate_srt_alert():
    # 3点は最下位「警報」、8点は「良」
    assert evaluate("srt", 3, age=38, sex="male")["label"] == "警報"
    assert evaluate("srt", 8, age=38, sex="male")["label"] == "良"


def test_evaluate_returns_reference():
    out = evaluate("push_up", 42, age=38, sex="male")
    assert "Yang" in out["reference"]


# ---- evaluate: 年齢/性別欠損フォールバック ----

def test_evaluate_none_without_sex():
    assert evaluate("push_up", 42, age=38, sex=None) is None


def test_evaluate_none_without_age():
    assert evaluate("push_up", 42, age=None, sex="male") is None


def test_evaluate_none_for_female():
    # 基準値は男性エビデンスベースなので女性はバンドを出さない
    assert evaluate("push_up", 42, age=38, sex="female") is None


def test_evaluate_none_value():
    assert evaluate("push_up", None, age=38, sex="male") is None


# ---- compute_trend: MDC で実変化/ノイズを区別 ----

def test_trend_real_change_pushup():
    # push_up の MDC=2。+2 は実変化
    t = compute_trend("push_up", 42, 40)
    assert t["is_real_change"] is True
    assert t["direction"] == "up"
    assert t["improved"] is True
    assert t["delta"] == 2


def test_trend_noise_pushup():
    # +1 は MDC 未満でノイズ
    t = compute_trend("push_up", 41, 40)
    assert t["is_real_change"] is False


def test_trend_grip_mdc():
    # grip の MDC=6。-5 はノイズ、-6 は実変化(悪化)
    assert compute_trend("grip", 42, 47)["is_real_change"] is False
    worse = compute_trend("grip", 41, 47)
    assert worse["is_real_change"] is True
    assert worse["improved"] is False


def test_trend_none_when_no_previous():
    assert compute_trend("push_up", 42, None) is None


# ---- compute_due: テストごとの間隔 ----

def test_due_pushup_monthly():
    last = date(2026, 5, 1)
    # 4週後 = 5/29。5/28 はまだ、5/29 で due
    assert compute_due("push_up", last, date(2026, 5, 28))["is_due"] is False
    assert compute_due("push_up", last, date(2026, 5, 29))["is_due"] is True


def test_due_srt_longer_interval():
    last = date(2026, 5, 1)
    # srt は 10週。push_up が due になる頃 (5/29) でも srt はまだ
    assert compute_due("srt", last, date(2026, 5, 29))["is_due"] is False
    # 10週 = 7/10
    assert compute_due("srt", last, date(2026, 7, 10))["is_due"] is True


def test_due_first_time_is_due():
    out = compute_due("push_up", None, date(2026, 6, 22))
    assert out["is_due"] is True
    assert out["last_on"] is None


# ---- grip_best ----

def test_grip_best_takes_max():
    assert grip_best(44.0, 47.0) == 47.0
    assert grip_best(47.0, None) == 47.0
    assert grip_best(None, None) is None


# ---- build_overview (DB) ----

def test_overview_first_run_all_due(db_engine):
    ov = build_overview(date(2026, 6, 22))
    # 記録ゼロなら全テスト due
    assert ov["any_due"] is True
    assert len(ov["tests"]) == len(FITNESS_TESTS)
    for t in ov["tests"]:
        assert t["latest"] is None
        assert t["due"]["is_due"] is True


def test_overview_reflects_latest_and_trend(db_engine):
    with session_scope() as s:
        s.add(FitnessTestResult(test_key="push_up", performed_on=date(2026, 6, 1), value=38))
        s.add(FitnessTestResult(test_key="push_up", performed_on=date(2026, 6, 20), value=42))
    ov = build_overview(date(2026, 6, 22))
    pu = next(t for t in ov["tests"] if t["definition"]["key"] == "push_up")
    assert pu["latest"]["value"] == 42
    assert pu["trend"]["delta"] == 4
    assert pu["trend"]["is_real_change"] is True
    # 6/20 + 4週 = 7/18 なのでまだ due でない
    assert pu["due"]["is_due"] is False

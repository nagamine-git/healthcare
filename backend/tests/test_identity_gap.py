"""Compass のギャップ算出と多角測定の EWMA 合成テスト (DB 非依存)。"""

from __future__ import annotations

from app.scoring.identity import gap


def test_proximity_reaches_100_at_target() -> None:
    assert gap.proximity_to_target(90, 90) == 100.0
    assert gap.proximity_to_target(100, 90) == 100.0  # 目標超過は 100 に張り付く
    # 目標の半分なら近さも約半分。
    assert gap.proximity_to_target(45, 90) == 50.0
    assert gap.proximity_to_target(0, 90) == 0.0


def test_proximity_none_passthrough() -> None:
    assert gap.proximity_to_target(None, 90) is None


def test_dimension_gap_floored_at_zero() -> None:
    assert gap.dimension_gap(40, 90) == 50.0
    assert gap.dimension_gap(95, 90) == 0.0  # 目標到達後は伸びしろ 0
    assert gap.dimension_gap(None, 90) is None


def test_signal_to_observation_centers_on_baseline() -> None:
    base = 50.0
    assert gap.signal_to_observation(base, 0.0) == 50.0
    assert gap.signal_to_observation(base, 1.0) == 50.0 + gap.SIGNAL_SCALE
    assert gap.signal_to_observation(base, -1.0) == 50.0 - gap.SIGNAL_SCALE
    # クランプされる。
    assert gap.signal_to_observation(95.0, 1.0) == 100.0
    assert gap.signal_to_observation(5.0, -1.0) == 0.0


def test_blend_current_no_observations_returns_baseline() -> None:
    assert gap.blend_current(60.0, []) == 60.0
    assert gap.blend_current(60.0, None) == 60.0


def test_blend_current_pulls_toward_observations() -> None:
    # ベースライン低め + 高い観測が続けば現在地は上振れする。
    out = gap.blend_current(30.0, [80.0, 80.0, 80.0], span=4)
    assert out is not None
    assert 30.0 < out < 80.0
    # ベースラインだけより明確に高い。
    assert out > 40.0


def test_blend_current_without_baseline_uses_observations() -> None:
    assert gap.blend_current(None, [70.0, 70.0]) == 70.0
    assert gap.blend_current(None, []) is None


def test_identity_alignment_geometric_pull() -> None:
    targets = {"a": 100.0, "b": 100.0}
    weights = {"a": 1.0, "b": 1.0}
    # 片方が極端に低いと幾何平均で全体が引っ張られる (弱点を放置しない)。
    balanced = gap.identity_alignment({"a": 80.0, "b": 80.0}, targets, weights)
    lopsided = gap.identity_alignment({"a": 100.0, "b": 60.0}, targets, weights)
    assert balanced is not None and lopsided is not None
    assert lopsided < balanced


def test_compute_gap_report_structure_and_ranking() -> None:
    targets = {"ownership": 90.0, "growth_mindset": 90.0, "self_direction": 90.0}
    weights = {"ownership": 2.0, "growth_mindset": 1.0, "self_direction": 1.0}
    currents = {"ownership": 40.0, "growth_mindset": 80.0, "self_direction": None}
    report = gap.compute_gap_report(currents, targets, weights)

    assert set(report) == {"dimensions", "layers", "overall", "weakest"}
    assert len(report["dimensions"]) == 3
    # 最大ギャップ (ownership: 50) が weakest 先頭。
    assert report["weakest"][0] == "ownership"
    # current=None の次元はギャップ算出不能なので weakest に含まれない。
    assert "self_direction" not in report["weakest"]
    # layer 集計が出ている。
    assert "values" in report["layers"]
    assert "mindset" in report["layers"]

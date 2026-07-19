from __future__ import annotations

from app.scoring.training_split import compute_today_training, strength_split


def test_strength_split_rotates_push_pull_legs():
    assert strength_split(strength_total=0, day_ordinal=0)["pattern"] == "push"
    assert strength_split(strength_total=1, day_ordinal=0)["pattern"] == "pull"
    assert strength_split(strength_total=2, day_ordinal=0)["pattern"] == "legs"
    assert strength_split(strength_total=3, day_ordinal=0)["pattern"] == "push"  # 一周


def test_strength_split_has_fixed_mains_and_rotating_accessory():
    a = strength_split(strength_total=0, day_ordinal=0)
    b = strength_split(strength_total=0, day_ordinal=1)
    # 主種目は固定 (漸進のため)、補助は日替わり
    assert a["main_lifts"] == b["main_lifts"]
    assert len(a["main_lifts"]) == 2
    assert a["accessory"] != b["accessory"]


def test_strength_split_alternates_dumbbell_and_bodyweight():
    db = strength_split(strength_total=0, day_ordinal=0)   # DB (push)
    bw = strength_split(strength_total=1, day_ordinal=0)   # 自重 (pull)
    assert db["mode"] == "dumbbell"
    assert bw["mode"] == "bodyweight"
    assert any("ダンベル" in m for m in db["main_lifts"])
    assert any(("懸垂" in m or "インバーテッド" in m) for m in bw["main_lifts"])
    # 自重 push も出る (total=3 → push・自重)
    bw_push = strength_split(strength_total=3, day_ordinal=0)
    assert bw_push["pattern"] == "push" and bw_push["mode"] == "bodyweight"
    assert any("腕立て" in m for m in bw_push["main_lifts"])


def test_today_picks_strength_when_strength_deficit_larger():
    # 筋トレ0/3・有酸素3/3 → 筋トレ不足が大 → strength
    t = compute_today_training(strength_7d=0, cardio_7d=3, strength_total=0, day_ordinal=0)
    assert t["modality"] == "strength"
    assert t["split"]["pattern"] == "push"


def test_today_picks_cardio_when_cardio_deficit_larger():
    # 筋トレ3/3・有酸素0/3 → 有酸素不足が大 → cardio ローテ先頭 (kata)
    t = compute_today_training(strength_7d=3, cardio_7d=0, strength_total=3, day_ordinal=0)
    assert t["modality"] == "kata"
    assert "素振り" in t["detail"]


def test_cardio_rotation_kata_hiit_z2():
    assert compute_today_training(strength_7d=3, cardio_7d=0, strength_total=0,
                                  day_ordinal=0)["modality"] == "kata"
    assert compute_today_training(strength_7d=3, cardio_7d=1, strength_total=0,
                                  day_ordinal=0)["modality"] == "hiit"
    assert compute_today_training(strength_7d=3, cardio_7d=2, strength_total=0,
                                  day_ordinal=0)["modality"] == "z2"


def test_tie_prefers_strength():
    # 不足が同点 (両方 0 done) → 体組成の核=筋トレ優先
    t = compute_today_training(strength_7d=0, cardio_7d=0, strength_total=0, day_ordinal=0)
    assert t["modality"] == "strength"

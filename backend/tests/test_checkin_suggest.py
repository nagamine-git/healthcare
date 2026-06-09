from __future__ import annotations


def test_energy_from_body_battery():
    from app.scoring.checkin_suggest import estimate_subjective

    s = estimate_subjective(body_battery=90, stress_avg=None,
                            sleep_score=None, training_load_48h=None)
    assert s["energy"] == 5
    s2 = estimate_subjective(body_battery=30, stress_avg=None,
                             sleep_score=None, training_load_48h=None)
    assert s2["energy"] == 2


def test_stress_from_garmin_bands():
    from app.scoring.checkin_suggest import estimate_subjective

    # Garmin: 0-25 休息→1、76-100 高→5
    assert estimate_subjective(body_battery=None, stress_avg=15,
                               sleep_score=None, training_load_48h=None)["stress"] == 1
    assert estimate_subjective(body_battery=None, stress_avg=80,
                               sleep_score=None, training_load_48h=None)["stress"] == 5


def test_soreness_from_training_load():
    from app.scoring.checkin_suggest import estimate_subjective

    none_load = estimate_subjective(body_battery=None, stress_avg=None,
                                    sleep_score=None, training_load_48h=0)
    assert none_load["soreness"] == 1
    high_load = estimate_subjective(body_battery=None, stress_avg=None,
                                    sleep_score=None, training_load_48h=350)
    assert high_load["soreness"] == 5


def test_energy_blends_body_battery_and_readiness():
    from app.scoring.checkin_suggest import estimate_subjective

    # BB 85 -> 5、readiness 50 -> 3 → 平均 4
    s = estimate_subjective(body_battery=85, stress_avg=None, sleep_score=None,
                            training_load_48h=None, training_readiness=50)
    assert s["energy"] == 4
    # BB が無く readiness のみでも活力を出せる
    s2 = estimate_subjective(body_battery=None, stress_avg=None, sleep_score=None,
                             training_load_48h=None, training_readiness=90)
    assert s2["energy"] == 5


def test_mood_is_composite_and_none_without_inputs():
    from app.scoring.checkin_suggest import estimate_subjective

    # 入力が全く無ければ mood は None
    empty = estimate_subjective(body_battery=None, stress_avg=None,
                                sleep_score=None, training_load_48h=None)
    assert empty["mood"] is None
    # 良い睡眠 + 高BB + 低ストレス → mood 高め
    good = estimate_subjective(body_battery=85, stress_avg=20, sleep_score=85,
                               training_load_48h=None)
    assert good["mood"] is not None and good["mood"] >= 4


def test_missing_proxy_returns_none():
    from app.scoring.checkin_suggest import estimate_subjective

    s = estimate_subjective(body_battery=None, stress_avg=None,
                            sleep_score=None, training_load_48h=None)
    assert s["energy"] is None and s["stress"] is None and s["soreness"] is None

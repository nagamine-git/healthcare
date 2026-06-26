from __future__ import annotations

from app.scoring.checkup import abnormal_summary, evaluate, flag_value

ITEMS = [
    {"key": "ldl_c", "label": "LDLコレステロール", "unit": "mg/dL", "category": "脂質", "lo": None, "hi": 119},
    {"key": "hdl_c", "label": "HDLコレステロール", "unit": "mg/dL", "category": "脂質", "lo": 40, "hi": None},
    {"key": "hba1c", "label": "HbA1c", "unit": "%", "category": "血糖", "lo": None, "hi": 5.5},
]


def test_flag_value_bands():
    assert flag_value(150, None, 119) == "high"
    assert flag_value(100, None, 119) == "normal"
    assert flag_value(35, 40, None) == "low"
    assert flag_value(None, 40, None) == "unknown"


def test_evaluate_filters_unknown_keys_and_flags():
    raw = [
        {"key": "ldl_c", "value": 150, "unit": "mg/dL"},
        {"key": "hba1c", "value": 5.2, "unit": "%"},
        {"key": "junk", "value": 1, "unit": "x"},  # catalog外→捨てる
    ]
    out = evaluate(raw, ITEMS)
    keys = {o["key"]: o["flag"] for o in out}
    assert keys == {"ldl_c": "high", "hba1c": "normal"}


def test_abnormal_summary():
    out = evaluate([{"key": "ldl_c", "value": 150, "unit": "mg/dL"}], ITEMS)
    assert "LDL" in abnormal_summary(out)
    assert abnormal_summary([{"label": "x", "value": 1, "unit": "", "flag": "normal"}]).startswith("健診")

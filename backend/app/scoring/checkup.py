"""健康診断値のフラグ判定(純関数・DB非依存)。"""

from __future__ import annotations


def flag_value(value: float | None, lo: float | None, hi: float | None) -> str:
    """基準band [lo,hi] に対し low / high / normal を返す(片側は None)。"""
    if value is None:
        return "unknown"
    if lo is not None and value < lo:
        return "low"
    if hi is not None and value > hi:
        return "high"
    return "normal"


def evaluate(raw_values: list[dict], items: list[dict]) -> list[dict]:
    """抽出値(key,value,unit)を基準項目で評価し flag/label/category を付与。

    catalog に無いキーは捨てる(科学的に有効な項目に絞る)。
    """
    by_key = {it["key"]: it for it in items}
    out = []
    for rv in raw_values:
        it = by_key.get(rv.get("key"))
        if it is None:
            continue
        val = rv.get("value")
        out.append({
            "key": it["key"],
            "label": it["label"],
            "category": it["category"],
            "value": val,
            "unit": it["unit"],
            "flag": flag_value(val, it.get("lo"), it.get("hi")),
        })
    return out


def abnormal_summary(values: list[dict]) -> str:
    """異常値(low/high)を一言サマリに(LLM コーチング文脈・表示用)。"""
    abn = [v for v in values if v.get("flag") in ("low", "high")]
    if not abn:
        return "健診の主要項目はすべて基準内。"
    parts = [f"{v['label']}{v['value']}{v['unit']}({'高' if v['flag'] == 'high' else '低'})" for v in abn]
    return "要注意: " + " / ".join(parts)

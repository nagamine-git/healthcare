"""LLM で食品名+量からマクロ (kcal/P/F/C/単位) を推定する。

素人が栄養成分を手入力する摩擦を消すための用途。LLM は「食品名→代表的なマクロ」
の推定だけを担い、不足分や収支の計算は決定的に行う (LLM に算術はさせない)。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings

ESTIMATE_TOOL: dict[str, Any] = {
    "name": "submit_food_macros",
    "description": (
        "食品名と量から、その量あたりの栄養 (kcal/タンパク質/脂質/炭水化物) を日本の"
        "一般的な食品・市販品の標準値で推定して提出する。過度に細かくせず妥当な代表値で。"
    ),
    "input_schema": {
        "type": "object",
        "required": ["kcal", "protein_g", "fat_g", "carb_g", "unit_label", "category", "is_protein_source"],
        "properties": {
            "kcal": {"type": "number", "description": "指定量あたりの推定カロリー(kcal)"},
            "protein_g": {"type": "number", "description": "タンパク質(g)"},
            "fat_g": {"type": "number", "description": "脂質(g)"},
            "carb_g": {"type": "number", "description": "炭水化物(g)"},
            "unit_label": {
                "type": "string",
                "description": "1単位の表現(例 '1個','1杯(200ml)','100g')。入力の量をそのまま1単位とする",
            },
            "category": {
                "type": "string",
                "enum": ["主食", "主菜", "副菜", "間食", "飲料", "タンパク源", "その他"],
            },
            "is_protein_source": {
                "type": "boolean",
                "description": "タンパク質が主な食品(肉/魚/卵/乳/プロテイン/大豆製品等)なら true",
            },
        },
    },
}

_SYSTEM = (
    "あなたは管理栄養士です。日本の一般的な食品・市販品の標準的な栄養成分から、"
    "与えられた食品と量のマクロを推定し、submit_food_macros を必ず1回呼びます。"
    "迷ったら一般的な1食/1個分の代表値を用い、過度に細かくしないこと。"
)


async def _anthropic_estimate(
    name: str, qty_text: str | None, *, model: str, api_key: str
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    msg = f"食品: {name}\n量: {qty_text or '一般的な1食/1個分'}\nこの量あたりの栄養を推定してください。"
    resp = await client.messages.create(
        model=model,
        max_tokens=400,
        system=_SYSTEM,
        messages=[{"role": "user", "content": msg}],
        tools=[ESTIMATE_TOOL],
        tool_choice={"type": "tool", "name": "submit_food_macros"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_food_macros":
            if isinstance(block.input, dict):
                return block.input
    return {}


# テストはこれを差し替える (ネットワーク非依存)。
_estimate = _anthropic_estimate


async def estimate_food_macros(name: str, qty_text: str | None = None) -> dict[str, Any] | None:
    """食品名(+量)から1単位あたりのマクロ推定を返す。API キー未設定/失敗時 None。"""
    s = get_settings()
    api_key = getattr(s, "anthropic_api_key", None)
    if not api_key:
        return None
    try:
        out = await _estimate(name, qty_text, model=s.llm_model, api_key=api_key)
    except Exception:
        return None
    if not out or "kcal" not in out:
        return None
    return {
        "name": name,
        "kcal": round(float(out.get("kcal", 0)), 1),
        "protein_g": round(float(out.get("protein_g", 0)), 1),
        "fat_g": round(float(out.get("fat_g", 0)), 1),
        "carb_g": round(float(out.get("carb_g", 0)), 1),
        "unit_label": out.get("unit_label") or (qty_text or "1食"),
        "category": out.get("category") or "その他",
        "is_protein_source": bool(out.get("is_protein_source", False)),
    }

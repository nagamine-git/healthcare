"""LLM で品目名/URL/画像から ROI候補の各項目を推定する(根拠つき)。

購入検討品目の手入力摩擦を消す用途。LLM は「品目→代表的な相場・耐用・削減見込み」の
推定だけを担い、スコア計算は既存の決定的ロジック(scoring/finance.py)が行う。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_PERIODS = {"onetime", "month", "year"}

ROI_TOOL: dict[str, Any] = {
    "name": "submit_roi",
    "description": (
        "購入検討品目について、ROI試算に必要な各項目を日本の一般的な相場・使用実態から"
        "推定して提出する。主観項目(削減時間/収益/活用日)も控えめな代表値で叩き台を出し、"
        "各項目に短い推定根拠(reasons)を添える。"
    ),
    "input_schema": {
        "type": "object",
        "required": ["cost_jpy", "period", "monthly_use_days", "monthly_time_saved_h",
                     "monthly_revenue_jpy", "resale_jpy", "reasons"],
        "properties": {
            "cost_jpy": {"type": "number", "description": "価格(円)。サブスクは1期間額"},
            "period": {"type": "string", "enum": ["onetime", "month", "year"],
                       "description": "買い切り=onetime / 月額=month / 年額=year"},
            "monthly_use_days": {"type": "number", "description": "月あたり使用日数(0-31)"},
            "monthly_time_saved_h": {"type": "number", "description": "月あたり削減時間(h)。控えめに"},
            "monthly_revenue_jpy": {"type": "number", "description": "月あたり増加収益(円)。無ければ0"},
            "resale_jpy": {"type": "number", "description": "想定売却額/資産性(円)"},
            "url": {"type": "string", "description": "商品/参考URL(分かれば)"},
            "note": {"type": "string", "description": "一言メモ(用途/前提)"},
            "reasons": {
                "type": "object",
                "description": "各項目の1行根拠(キーは項目名: cost_jpy 等)",
                "additionalProperties": {"type": "string"},
            },
        },
    },
}

_SYSTEM = (
    "あなたは購買判断のアドバイザーです。ユーザーが検討中の品目について、ROI試算に必要な"
    "各項目を日本の一般的な相場・市販価格・使用実態から推定し、submit_roi を必ず1回呼びます。"
    "主観項目(削減時間/収益/活用日)は過大にせず控えめな代表値で叩き台を出し、reasons に"
    "各項目の短い根拠を書きます。ユーザーの既存候補(相場観)が与えられたら参考にします。"
)


async def _anthropic_suggest(
    *, name: str | None, url: str | None, image_b64: str | None, media_type: str,
    context: str, model: str, api_key: str,
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    parts: list[dict[str, Any]] = []
    if image_b64:
        parts.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type, "data": image_b64}})
    desc: list[str] = []
    if name:
        desc.append(f"品目名: {name}")
    if url:
        desc.append(f"URL: {url}")
    if not desc:
        desc.append("(画像を参照)")
    parts.append({"type": "text", "text": "\n".join(desc) + "\n\nこの品目のROI項目を推定してください。"})
    system = _SYSTEM + (f"\n\n# ユーザーの既存候補(相場観)\n{context}" if context else "")
    resp = await client.messages.create(
        model=model, max_tokens=700, system=system,
        messages=[{"role": "user", "content": parts}],
        tools=[ROI_TOOL], tool_choice={"type": "tool", "name": "submit_roi"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_roi":
            if isinstance(block.input, dict):
                return block.input
    return {}


# テストで差し替える(ネットワーク非依存)。
_suggest = _anthropic_suggest


def _num(v: Any, lo: float = 0.0, hi: float | None = None) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return lo
    if n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return round(n, 2)


async def suggest_roi(
    *, name: str | None = None, url: str | None = None,
    image_b64: str | None = None, media_type: str = "image/png",
    context: str = "",
) -> dict[str, Any] | None:
    """品目名/URL/画像から ROI項目を推定して {fields, reasons} を返す。

    APIキー未設定/入力なし/失敗時は None。fields は型/enum正規化済み(そのまま prefill 可)。
    """
    s = get_settings()
    api_key = getattr(s, "anthropic_api_key", None)
    if not api_key:
        return None
    if not (name or url or image_b64):
        return None
    try:
        raw = await _suggest(
            name=name, url=url, image_b64=image_b64, media_type=media_type,
            context=context, model=s.llm_model, api_key=api_key,
        )
    except Exception as exc:
        logger.warning("roi_suggest_failed", error=str(exc))
        return None
    if not raw:
        return None
    period = raw.get("period")
    if period not in _PERIODS:
        period = "onetime"
    fields = {
        "cost_jpy": _num(raw.get("cost_jpy")),
        "period": period,
        "monthly_use_days": _num(raw.get("monthly_use_days"), 0.0, 31.0),
        "monthly_time_saved_h": _num(raw.get("monthly_time_saved_h")),
        "monthly_revenue_jpy": _num(raw.get("monthly_revenue_jpy")),
        "resale_jpy": _num(raw.get("resale_jpy")),
        "url": (raw.get("url") or url or None),
        "note": (raw.get("note") or None),
    }
    reasons = raw.get("reasons") if isinstance(raw.get("reasons"), dict) else {}
    return {"fields": fields, "reasons": reasons}


# ---------------- 欲しいものリスト(wishlist)一括抽出 ----------------
WISHLIST_TOOL: dict[str, Any] = {
    "name": "submit_wishlist",
    "description": "欲しいものリスト(HTML/スクショ)から各商品の名前・価格(円)・URLを抽出する。",
    "input_schema": {
        "type": "object",
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string", "description": "商品名"},
                        "price_jpy": {"type": "number", "description": "価格(円)。分かれば"},
                        "url": {"type": "string", "description": "商品URL。分かれば"},
                    },
                },
            },
        },
    },
}

_WISHLIST_SYSTEM = (
    "あなたはECの欲しいものリストから購入候補を抜き出すアシスタントです。与えられた"
    "HTMLまたはスクリーンショットから、各商品の名前・価格(円)・URLを抽出し submit_wishlist を"
    "必ず1回呼びます。ナビ/広告/おすすめ/関連商品など、リスト本体でないものは除外します。"
)


async def _anthropic_extract_wishlist(
    *, content: str | None, image_b64: str | None, media_type: str, model: str, api_key: str,
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    parts: list[dict[str, Any]] = []
    if image_b64:
        parts.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type, "data": image_b64}})
    if content:
        parts.append({"type": "text", "text": content[:60000]})  # HTML が巨大なので上限
    parts.append({"type": "text", "text": "この欲しいものリストから商品を抽出してください。"})
    resp = await client.messages.create(
        model=model, max_tokens=2000, system=_WISHLIST_SYSTEM,
        messages=[{"role": "user", "content": parts}],
        tools=[WISHLIST_TOOL], tool_choice={"type": "tool", "name": "submit_wishlist"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_wishlist":
            if isinstance(block.input, dict):
                return block.input
    return {}


_extract_wishlist = _anthropic_extract_wishlist


async def extract_wishlist_items(
    *, html: str | None = None, image_b64: str | None = None, media_type: str = "image/png",
) -> list[dict[str, Any]]:
    """欲しいものリスト(HTML/画像)から候補[{name, cost_jpy, period, url}]を抽出。失敗時 []。"""
    s = get_settings()
    api_key = getattr(s, "anthropic_api_key", None)
    if not api_key or not (html or image_b64):
        return []
    try:
        raw = await _extract_wishlist(
            content=html, image_b64=image_b64, media_type=media_type,
            model=s.llm_model, api_key=api_key,
        )
    except Exception as exc:
        logger.warning("wishlist_extract_failed", error=str(exc))
        return []
    src = raw.get("items", []) if isinstance(raw, dict) else []
    items: list[dict[str, Any]] = []
    for it in src:
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        items.append({
            "name": name,
            "cost_jpy": _num(it.get("price_jpy")),
            "period": "onetime",
            "url": (it.get("url") or None),
        })
    return items

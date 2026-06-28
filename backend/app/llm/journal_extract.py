"""控え(ジャーナルのテキスト)から「その日にやった良い行動」を保守的に抽出する。

OCR×LLM 推定は誤りやすい前提。返すのは**提案**であり、記録は必ず人の確認を経る
(api 側で commit)。api_key 未設定/失敗時は None。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = """\
あなたは日次ジャーナルの読み手です。手書きを起こしたテキストから、その日に**実際に実行された
良い行動**だけを保守的に抽出します。これはユーザーの健康・成長スコアに反映されるため、
**推測で水増ししない**ことが最優先です。

# 指示
- 候補カテゴリ(kind とラベル)は与えられたリストの中からのみ選ぶ。リスト外は出さない。
- **明確に「やった」と読める記述だけ**を拾う。予定/願望/未完(未チェックの □、「やりたい」等)は除外。
- 各抽出について evidence(根拠となった原文の短い一節)を必ず添える。
- confidence: 完了マーク(☑/済/「〜した」)や時刻つき実績など明確なら "high"、
  文脈から推測できるが断定しづらいものは "med"、弱い手がかりは "low"。
- 同じ kind は1回だけ。該当が無ければ空配列。
必ず submit_actions ツールで返すこと。
"""

EXTRACT_TOOL: dict[str, Any] = {
    "name": "submit_actions",
    "description": "控えから読み取れた『やった良い行動』を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "description": "候補リストの kind"},
                        "evidence": {"type": "string", "description": "根拠となった原文の短い一節"},
                        "confidence": {"type": "string", "enum": ["high", "med", "low"]},
                    },
                    "required": ["kind", "evidence", "confidence"],
                },
            }
        },
        "required": ["actions"],
    },
}


async def extract_actions(text: str, catalog: list[dict]) -> list[dict] | None:
    """text から良い行動を抽出。catalog は {kind,label} のリスト。kind は catalog に限定。"""
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key or not text.strip():
        return None
    allowed = {c["kind"] for c in catalog}
    menu = "\n".join(f"- {c['kind']}: {c['label']}" for c in catalog)
    user = f"# 候補カテゴリ(この中からのみ)\n{menu}\n\n# 控え本文\n{text[:6000]}"
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            tools=[EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "submit_actions"},
        )
    except Exception as exc:
        logger.warning("journal_extract_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_actions":
            inp = block.input
            if isinstance(inp, dict):
                actions = inp.get("actions", [])
                # catalog 外・重複 kind を除外(保険)。
                seen: set[str] = set()
                out: list[dict] = []
                for a in actions:
                    k = a.get("kind")
                    if k in allowed and k not in seen:
                        seen.add(k)
                        out.append(a)
                return out
    return None

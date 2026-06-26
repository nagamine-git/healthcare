"""健康診断結果(テキスト/画像)から科学的に有効な項目を構造化抽出する。

Claude(vision 対応)で抽出。api_key 未設定/失敗時は None(呼び出し側でエラー応答)。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = """\
あなたは健康診断結果を読み取る専門家です。与えられたテキストまたは画像から、下記の
科学的に有効な項目だけを数値で抽出します。該当しない/読めない項目は出さない。
単位は結果記載のものに合わせる。検査日が分かれば date(YYYY-MM-DD)を返す。
必ず submit_checkup ツールで返すこと。
"""


def _tool(keys: list[str]) -> dict[str, Any]:
    return {
        "name": "submit_checkup",
        "description": "健康診断から有効項目を構造化抽出する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": ["string", "null"], "description": "検査日 YYYY-MM-DD"},
                "values": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "enum": keys},
                            "value": {"type": "number"},
                            "unit": {"type": "string"},
                        },
                        "required": ["key", "value", "unit"],
                    },
                },
            },
            "required": ["values"],
        },
    }


async def extract_checkup(
    *, text: str | None = None, image_b64: str | None = None, media_type: str = "image/png"
) -> dict | None:
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        return None
    keys = [it["key"] for it in settings.checkup_items]
    catalog = "\n".join(f"- {it['key']}: {it['label']} ({it['unit']})" for it in settings.checkup_items)

    content: list[dict[str, Any]] = []
    if image_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
        })
    user_text = f"抽出対象の項目:\n{catalog}\n\n"
    if text:
        user_text += f"結果テキスト:\n{text}"
    else:
        user_text += "添付画像の健康診断結果から抽出してください。"
    content.append({"type": "text", "text": user_text})

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=1500,
            system=_SYSTEM,
            messages=[{"role": "user", "content": content}],
            tools=[_tool(keys)],
            tool_choice={"type": "tool", "name": "submit_checkup"},
        )
    except Exception as exc:
        logger.warning("checkup_extract_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_checkup":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return None

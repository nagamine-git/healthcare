"""手書きジャーナルの写真を文字起こしする(ベストエフォート)。

字が汚い前提なので**鵜呑みにしない**運用。必ず画面で確認・修正してから保存させる。
api_key 未設定/失敗時は None。
"""

from __future__ import annotations

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = """\
あなたは手書きノートの文字起こしの専門家です。日本語のバレットジャーナルの写真を、
できるだけ忠実にプレーンテキスト(Markdown)へ書き起こします。

# 指示
- 見出し・箇条書き・スケジュールなどの構造は保つ。
- **読めない/自信がない箇所は推測で埋めず `[?]` を置く**(誤りを混ぜない)。
- 余計な解釈・要約・補完はしない。書かれている文字をそのまま起こす。
- 結果は本文テキストのみ(前置き不要)。
"""


async def transcribe_journal(*, image_b64: str, media_type: str = "image/png") -> str | None:
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=2000,
            system=_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                        },
                        {"type": "text", "text": "この手書きジャーナルを文字起こししてください。"},
                    ],
                }
            ],
        )
    except Exception as exc:
        logger.warning("journal_transcribe_failed", error=str(exc))
        return None
    parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    text = "".join(parts).strip()
    return text or None

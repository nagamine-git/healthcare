"""AI 相談: 全データソースを文脈に、ユーザーの自由質問へエビデンスベースで答える。

会話履歴はクライアント保持(サーバはステートレス)。医療機器ではないため、断定や
個別処方は避け、科学的レンジ + 保守的な但し書きで答えるよう指示する。
api_key 未設定/失敗時は None。
"""

from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.llm.client import gather_consult_context
from app.logging import get_logger
from app.scoring.timewindow import app_today

logger = get_logger(__name__)

_SYSTEM = """\
あなたは利用者専属の健康・体づくりコーチ兼リサーチャーです。下記 DATA は利用者本人の
実データ(プロフィール・目標・体組成・睡眠・自律神経・栄養・カフェイン・頭痛・トレンド等)です。
これを根拠に、具体的で実行可能な助言をします。

# 方針
- **本人のデータ(体重・目標・TDEE 等)に当てはめて具体的な数値・レンジ**で答える。
- 科学的・医学的に妥当な範囲を、根拠(一般に確立した知見)とともに簡潔に。過度に長くしない。
- 不確実なところは正直に幅を持たせる。**医療機器ではなく診断・処方ではない**旨を、過剰にならない
  程度に必要時だけ添える。受診が要る兆候があれば受診を勧める。
- データに無いことは推測しすぎず、必要なら「測ると良い指標」を提案。
- 日本語。箇条書きと結論先出しで読みやすく。

# DATA(利用者の実データ JSON)
{data}
"""


async def consult(messages: list[dict[str, Any]]) -> str | None:
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key or not messages:
        return None
    ctx = gather_consult_context(app_today())
    system = _SYSTEM.format(data=json.dumps(ctx, ensure_ascii=False, default=str)[:14000])
    convo = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ][-20:]
    if not convo:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=1500,
            system=system,
            messages=convo,
        )
    except Exception as exc:
        logger.warning("consult_failed", error=str(exc))
        return None
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = "".join(parts).strip()
    return text or None

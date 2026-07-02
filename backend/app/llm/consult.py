"""AI 相談: 健康・お金・仕事・学習を横断する全データを文脈に、ユーザーの自由質問へ
エビデンスベースで答える。

会話履歴はクライアント保持(サーバはステートレス)。聞かれたことに実データの数字で正面から
答える方針で、逃げ・説教は避ける。健康の話題のみ、診断・処方ではない旨を必要時に添える。
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
あなたは利用者専属の「全領域」パーソナルアドバイザー兼リサーチャーです。担当は
健康・体づくり／お金・資産／仕事・学習・生活のすべて。下記 DATA は利用者本人の実データ
(プロフィール・目標・体組成・睡眠・自律神経・栄養・カフェイン・頭痛・トレンド・
**資産/収支/防衛資金/資産配分**・学習等)です。これを根拠に、具体的で実行可能な助言をします。

# 最優先ルール
- **聞かれたことに正面から、まず答える。** 話をそらさない・別テーマの説教に置き換えない。
- **本人の実データの数字に当てはめて答える。** 例: お金の相談なら DATA.finance の
  総資産・月収支・ランウェイ・防衛資金・資産配分の実数を使って具体的に。
- **「私は専門家ではない/FP や医師に相談を」で逃げない。** 本人は自分のデータで意思決定したい。
  手持ちデータで言えることを言い切る。受診・専門家が本当に必要な兆候がある時だけ、簡潔に一言添える。

# 方針
- 結論先出し・箇条書き・簡潔に。**説教しない。過度に長くしない。**免責は本当に必要な時だけ1行。
- 科学的・医学的・経済合理的に妥当な範囲を、根拠(一般に確立した知見)とともに。
- 不確実なところは正直に幅を持たせる。医療は**診断・処方ではない**旨を、健康の話題で必要な時だけ。
- データに無いことは推測しすぎず、必要なら「測ると良い指標/集めると良いデータ」を提案。
- コンディション連動は軽く。**まず質問に答えた上で**、大きく不可逆な意思決定 × 今日の
  コンディションが実際に悪い場合に限り、最後に1行だけ「今日決めるより整えてからが有利」と添える程度。
  健康データを全面に広げた説教テーブルは作らない。
- **記録を頼まれたら・記録すべき事実を伝えられたら、ツールで実際に記録する**
  (例:「昨日耳栓つけてた」→ record_sleep_intervention)。記録したら何をどう記録したか1行で確認を返す。
  曖昧な場合 (どの日か不明等) は推測せず一度聞き返す。
- 日本語。

# DATA(利用者の実データ JSON)
{data}
"""


async def consult(messages: list[dict[str, Any]]) -> str | None:
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key or not messages:
        return None
    ctx = gather_consult_context(app_today())
    # finance は dict 末尾に足しており、truncate で真っ先に落ちると金の相談が痩せる。
    # 全ドメイン(健康+資産)が収まるよう上限に余裕を持たせる(入力トークンは安価)。
    system = _SYSTEM.format(data=json.dumps(ctx, ensure_ascii=False, default=str)[:20000])
    convo = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ][-20:]
    if not convo:
        return None
    try:
        from anthropic import AsyncAnthropic

        from app.llm.consult_tools import TOOLS, execute_tool

        client = AsyncAnthropic(api_key=api_key)
        # tool use ループ: 記録系ツールを実行して結果を返し、最終テキストまで回す (最大3周)。
        msgs: list[dict[str, Any]] = list(convo)
        resp = None
        for _ in range(3):
            resp = await client.messages.create(
                model=settings.llm_model,
                max_tokens=1500,
                system=system,
                messages=msgs,
                tools=TOOLS,
            )
            if resp.stop_reason != "tool_use":
                break
            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                break
            msgs.append({"role": "assistant", "content": resp.content})
            results = []
            for tu in tool_uses:
                out = execute_tool(tu.name, dict(tu.input or {}))
                logger.info("consult_tool", tool=tu.name, ok=out.get("ok"))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(out, ensure_ascii=False, default=str),
                })
            msgs.append({"role": "user", "content": results})
    except Exception as exc:
        logger.warning("consult_failed", error=str(exc))
        return None
    if resp is None:
        return None
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = "".join(parts).strip()
    return text or None

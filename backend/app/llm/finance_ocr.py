"""MoneyForward 等の資産画面スクショ/CSV から、資産バケット(名前・金額)を抽出する。

保存前に確認する運用(誤読しうる前提)。api_key 未設定/失敗時は None。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = """\
あなたは資産管理アプリ(MoneyForward 等)のスクリーンショットを読み取る専門家です。
画面に出ている**資産の種別ごとの残高**を抽出します。

# 指示
- 各資産(預金/現金/株式/投資信託/暗号資産/年金/ポイント/不動産 等)の name と value(円)を返す。
- **name は「金融機関名 + 口座/銘柄名」を必ず結合**する(例: 「三菱UFJ銀行 普通」「Coincheck ビットコイン」)。
  同じ「普通」が複数機関にあるため、機関名を必ず前置して一意にすること。
- **同じ銘柄が複数行ある場合 (特定口座/NISA/つみたて等の口座違い) は絶対に合算せず、
  画面の行ごとに1件ずつ返す**。口座区分が画面に見えるなら name に含める
  (例: 「SBI証券 eMAXIS Slim 米国株式(S&P500) NISA」)。見えなければ同名のまま2件返してよい。
- 複数画面の一部であることがある。**見えている項目だけ**を漏れなく返す(残高¥0も含める)。
- 合計・前日比・グラフ凡例・ナビゲーションなど、種別残高でないものは出さない。
- value は円の整数(カンマ・¥は除く)。読めない項目は出さない。
必ず submit_assets ツールで返すこと。
"""

_TOOL: dict[str, Any] = {
    "name": "submit_assets",
    "description": "資産種別ごとの残高(name, value)を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "assets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "value": {"type": "number"}},
                    "required": ["name", "value"],
                },
            }
        },
        "required": ["assets"],
    },
}


async def extract_assets(*, image_b64: str, media_type: str = "image/png") -> list[dict] | None:
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": "この資産画面から種別ごとの残高を抽出してください。"},
                ],
            }],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_assets"},
        )
    except Exception as exc:
        logger.warning("finance_ocr_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_assets":
            inp = block.input
            if isinstance(inp, dict):
                return [a for a in inp.get("assets", []) if a.get("name") and a.get("value") is not None]
    return None

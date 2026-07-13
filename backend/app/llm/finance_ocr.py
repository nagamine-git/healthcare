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


_FIN_SYSTEM = """\
あなたは MoneyForward 等の家計/資産管理アプリのスクリーンショットを読み取る専門家です。
画面がどの種類でも(資産一覧 / 負債 / 家計簿=月の収支)、**見えているものだけ**を抽出します。

# 抽出対象
- assets: 資産の種別ごと残高(預金/株式/投資信託/暗号資産/年金/ポイント/不動産 等)。
  name は「金融機関名 + 口座/銘柄名」を結合し一意に。同じ銘柄が複数口座にあるなら合算せず行ごと。
  **口座区分(特定/一般/NISA/つみたてNISA/成長投資枠/iDeCo)が画面に見えるなら name に必ず含める**
  (例: 「SBI証券 eMAXIS Slim 米国株式(S&P500) NISA」「〜 特定」)。**見えない/読めない口座区分を
  『口座①』『口座②』等の連番で捏造しないこと**。区分不明なら銘柄名のみで(同名2件のまま)返す。
- debts: 負債(住宅ローン/カードローン/クレジットカード残高/奨学金 等)の name と value(円)。
- income_monthly / expense_monthly: 家計簿画面に「今月の収入/支出」があれば、その月額(円)。

# 確度 (confidence)
- 各項目に high/medium/low を付ける。数字がくっきり読め種別も明確 = high。
  かすれ/推測/種別が曖昧 = low。**自信が無いものは low にし、捏造しない**。
- flow_confidence は income/expense 全体の確度。

# 注意
- 合計・前日比・グラフ・ナビ等、内訳でないものは出さない。value は円の整数(カンマ/¥除く)。
- 画面に無い種類は空にする(資産だけの画面なら debts は空、収支は null)。
必ず submit_finance ツールで返すこと。
"""

_FIN_TOOL: dict[str, Any] = {
    "name": "submit_finance",
    "description": "スクショから資産/負債/月次収支を確度つきで返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "assets": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "value": {"type": "number"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]}}}},
            "debts": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "value": {"type": "number"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]}}}},
            "income_monthly": {"type": ["number", "null"]},
            "expense_monthly": {"type": ["number", "null"]},
            "flow_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    },
}


async def extract_finance(*, image_b64: str, media_type: str = "image/png") -> dict[str, Any] | None:
    """MoneyForward の任意画面から資産/負債/収支を確度つきで抽出。失敗/未設定は None。"""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=1200,
            system=_FIN_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": "この画面から資産/負債/収支を、確度をつけて抽出してください。"},
                ],
            }],
            tools=[_FIN_TOOL],
            tool_choice={"type": "tool", "name": "submit_finance"},
        )
    except Exception as exc:
        logger.warning("finance_ocr_finance_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_finance":
            inp = block.input
            if isinstance(inp, dict):
                return {
                    "assets": [a for a in (inp.get("assets") or []) if a.get("name") and a.get("value") is not None],
                    "debts": [d for d in (inp.get("debts") or []) if d.get("name") and d.get("value") is not None],
                    "income_monthly": inp.get("income_monthly"),
                    "expense_monthly": inp.get("expense_monthly"),
                    "flow_confidence": inp.get("flow_confidence") or "low",
                }
    return None

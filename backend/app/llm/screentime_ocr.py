"""iOS スクリーンタイムのスクショから使用時間を抽出する (スマホ依存トラッキング)。

Week 画面 (日平均/週合計/カテゴリ) と Day 画面 (当日合計) の両方に対応。
tool_use でスキーマを強制。日付解決のため today をプロンプトに渡す。api_key 無し/失敗は None。
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = """\
あなたは iOS「スクリーンタイム」画面のスクリーンショットを読み取る専門家です。
1枚から1期間分の使用時間を抽出します。

# 判定
- Day 画面 (「Yesterday, July 4」「Today」等、1日分): period_type="day"。
  daily_min = その日の合計 (大きな見出しの時間, 例 8h24m→504)。period_start = その日付。
- Week 画面 (「Daily Average」「Last Week's Average」等): period_type="week"。
  daily_min = **日平均**の時間 (大きな見出し, 例 7h37m→457)。total_min = 「Total Screen Time」の
  週合計 (例 53h20m→3200)。period_start = その週の**日曜** (iOS 週は日曜開始)。

# 抽出
- categories: 「Entertainment / Productivity & Finance / Other / Utilities」等、表示中のカテゴリ名と分。
- top_apps: 「Most Used」のアプリ名と分 (上位、見えている分だけ)。
- 時間はすべて**分**の整数に換算 (1h42m→102)。読めない項目は出さない。
- 日付は today を基準に西暦を補う (未来日にはしない)。

必ず submit_screentime ツールで返すこと。
"""

_TOOL: dict[str, Any] = {
    "name": "submit_screentime",
    "description": "スクリーンタイム1期間分を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "period_type": {"type": "string", "enum": ["day", "week"]},
            "period_start": {"type": "string", "description": "ISO 日付 (day=その日 / week=週の日曜)"},
            "daily_min": {"type": "number", "description": "1日あたり分 (day=当日合計 / week=日平均)"},
            "total_min": {"type": "number", "description": "期間合計分 (week のみ, 任意)"},
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "minutes": {"type": "number"}},
                    "required": ["name", "minutes"],
                },
            },
            "top_apps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "minutes": {"type": "number"}},
                    "required": ["name", "minutes"],
                },
            },
        },
        "required": ["period_type", "period_start", "daily_min"],
    },
}


async def extract_screentime(
    *, image_b64: str, media_type: str = "image/png", today: date_type | None = None
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    from app.scoring.timewindow import app_today

    today = today or app_today()
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": f"今日は {today.isoformat()} です。この画面から使用時間を抽出してください。"},
                ],
            }],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_screentime"},
        )
    except Exception as exc:
        logger.warning("screentime_ocr_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            inp = dict(block.input or {})
            if inp.get("period_type") in ("day", "week") and inp.get("period_start") and inp.get("daily_min"):
                return inp
    return None

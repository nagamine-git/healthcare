"""体組成計(Tanita 等 BIA)のスクショから、HealthKit 標準に無い指標を抽出する。

骨格筋量・内臓脂肪レベル・基礎代謝(BMR)のみ。体重/体脂肪率は別経路(Apple Health)で
取得済みなので抽出しない。OCR は誤りうる前提で、保存前に必ず人が確認する運用。
api_key 未設定/失敗時は None。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = """\
あなたは体組成計アプリのスクリーンショットを読み取る専門家です。画像から下記の数値だけを
正確に抽出します。読めない/該当しない項目は null。推測で埋めない。

# 抽出する項目(これ以外は出さない)
- skeletal_muscle_kg: 「骨格筋」の量 (kg)
- skeletal_muscle_pct: 「骨格筋」の率 (%)
- visceral_fat_level: 「内臓脂肪レベル」(level の数値)
- bmr_kcal: 「基礎代謝」(kcal)
- date: 測定日が画像にあれば YYYY-MM-DD、無ければ null

注意: 「皮下脂肪」「体脂肪」「部位別(両腕/体幹/両脚)」「体年齢」「BMI」「体重」は**抽出しない**。
骨格筋は部位別ではなく全身の値を採る。必ず submit_body_comp ツールで返すこと。
"""

_TOOL: dict[str, Any] = {
    "name": "submit_body_comp",
    "description": "体組成計スクショから骨格筋量・内臓脂肪・基礎代謝を抽出する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "skeletal_muscle_kg": {"type": ["number", "null"]},
            "skeletal_muscle_pct": {"type": ["number", "null"]},
            "visceral_fat_level": {"type": ["number", "null"]},
            "bmr_kcal": {"type": ["number", "null"]},
            "date": {"type": ["string", "null"]},
        },
        "required": [
            "skeletal_muscle_kg", "skeletal_muscle_pct", "visceral_fat_level",
            "bmr_kcal", "date",
        ],
    },
}


async def extract_body_comp(*, image_b64: str, media_type: str = "image/png") -> dict | None:
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=400,
            system=_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                        },
                        {"type": "text", "text": "このスクショから対象の数値を抽出してください。"},
                    ],
                }
            ],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_body_comp"},
        )
    except Exception as exc:
        logger.warning("body_comp_extract_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_body_comp":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return None

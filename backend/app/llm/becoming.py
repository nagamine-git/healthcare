"""「今日の一手」生成。becoming 状態(盲点・診断・コンディション)から
盲点ねらいの高レバレッジ行動 + if-then を LLM で作る。

api_key 未設定時は呼ばず None を返す(呼び出し側が構造化フォールバックを使う)。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = """\
あなたは起業家マインドのコーチです。利用者は「サラリーマンマインドが抜けない」のが盲点で、
偉大な起業家(founder)を理想にしています。今日の身体コンディション・直近のフライホイール
診断・いちばん埋めたい盲点次元をふまえ、**今日いちばん効く具体的な一手を1つだけ**提案します。

# 指示
- **theme(短い一言)+ move(具体タスク)**をセットで出す。`theme: move` が
  「起業家: ユーザー候補5人に連絡をとる」「探求者: Rust 3.3 を終わらせる」
  「成長: イーロンの自伝を5分読む」のように一行で読めること。theme は役割/状態の2〜5字。
- 抽象論や複数提案は禁止。今日のうちに実行できる**1つの具体行動**に絞る。
- **1日の早い時間に片付けられる、明確に「完了」と言える行動**にする(所要は長くても1〜2時間、
  できれば午前中〜早い時間に終えられる単位)。だらだら続く曖昧な目標やノルマにしない。
  達成すれば「今日はもう勝ち」と思えるもの。
- **着火しやすい形にする**: move は「まず◯分で着手できる」最初の一歩を含む形にする
  (例『まず5分イーロンの自伝を読む』)。開始の心理的ハードルを下げるのが狙い。
- ignite_minutes: 着火に**コミットする最小の分数**(既定5、コンディションが低い日や重い行動は2〜3)。
  「これだけやればOK・やめてもいい下限」として置く短い時間。
- ignite_kind: その一手を記録する行動カテゴリ。**「その次元に効く行動カテゴリ」から最も近いものを1つ**
  選ぶ(該当が無ければ空文字)。
- 盲点次元(bottleneck)を前進させる行動を選ぶ。
- if_then は「◯◯したら、△△する」の実行意図フォーマット(朝/始業直後など早い起点を優先)。
- コンディションが低い日は負荷を下げた一手にする。
- 日本語。move は1文、rationale は1文。
必ず submit_one_move ツールで返すこと。
"""

ONE_MOVE_TOOL: dict[str, Any] = {
    "name": "submit_one_move",
    "description": "今日の高レバレッジな一手を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "theme": {
                "type": "string",
                "description": "今日の自分を表す短い一言テーマ(2〜5字、役割/状態)。"
                "例: 復活 / 起業家 / 探求者 / 成長。『テーマ: タスク』で読めるように。",
            },
            "move": {"type": "string", "description": "今日の具体的な一手(1文、早く完了できる単位)"},
            "if_then": {"type": "string", "description": "実行意図『◯◯したら、△△する』"},
            "ignite_minutes": {
                "type": "integer",
                "description": "着火にコミットする最小の分数(2〜10、既定5、重い日は2〜3)。",
            },
            "ignite_kind": {
                "type": "string",
                "description": "この一手を記録する行動カテゴリ(提示された候補から1つ、無ければ空文字)。",
            },
            "dimension_id": {"type": "string", "description": "狙う盲点次元のid"},
            "rationale": {"type": "string", "description": "なぜ効くか(1文)"},
        },
        "required": [
            "theme", "move", "if_then", "ignite_minutes", "ignite_kind",
            "dimension_id", "rationale",
        ],
    },
}


async def generate_one_move(state: dict) -> dict | None:
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        return None
    from anthropic import AsyncAnthropic

    user = (
        f"今日のコンディション: {state.get('condition')}\n"
        f"フライホイール診断: {state.get('diagnosis')}\n"
        f"いちばん埋めたい盲点次元: {state.get('bottleneck_id')} "
        f"({state.get('bottleneck_name')} — {state.get('bottleneck_desc')})\n"
        f"その次元に効く行動カテゴリ: {', '.join(state.get('kinds', [])) or 'なし'}\n"
        f"健康診断の所見: {state.get('checkup') or '未取込'}"
    )
    try:
        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            tools=[ONE_MOVE_TOOL],
            tool_choice={"type": "tool", "name": "submit_one_move"},
        )
    except Exception as exc:
        logger.warning("becoming_one_move_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_one_move":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return None

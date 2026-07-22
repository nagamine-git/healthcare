"""種目ごとの詳しいステップ式フォームガイドを LLM で生成する (タップ時のみ、ExerciseGuide に永続化)。

setup/execution/breathing/mistakes/tips の5区分・各箇条書きで、関節角度・可動域・目線・
呼吸のタイミング・よくある代償動作まで具体的に出させる。腰の既往 (config.user_injury_notes)
を踏まえて安全側に倒す。医療アドバイスではなく一般的な運動フォームの範囲に留める
(このアプリの非医療スタンス — SPEC.md 参照)。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings

_STEP_KEYS = ("setup", "execution", "breathing", "mistakes", "tips")


_TOOL: dict[str, Any] = {
    "name": "submit_exercise_guide",
    "description": "種目の詳しいステップ式フォームガイドを、区分ごとの箇条書きで提出する。",
    "input_schema": {
        "type": "object",
        "required": list(_STEP_KEYS),
        "properties": {
            "setup": {
                "type": "array",
                "items": {"type": "string"},
                "description": "開始姿勢・器具の握り方/セット位置・スタンス幅など (3〜6項目)",
            },
            "execution": {
                "type": "array",
                "items": {"type": "string"},
                "description": "動作の実行手順。関節角度・可動域・軌道・目線を具体的に (3〜6項目)",
            },
            "breathing": {
                "type": "array",
                "items": {"type": "string"},
                "description": "呼吸のタイミング (吸う/吐くをどの局面で行うか) (3〜6項目)",
            },
            "mistakes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "よくある代償動作・フォーム崩れとその見分け方 (3〜6項目)",
            },
            "tips": {
                "type": "array",
                "items": {"type": "string"},
                "description": "効かせるコツ・セルフチェック方法 (3〜6項目)",
            },
        },
    },
}

_SYSTEM_TEMPLATE = """\
あなたは利用者専属のパーソナルトレーナーです。指定された種目の**詳しいステップ式フォームガイド**を
submit_exercise_guide で必ず1回提出します。

# 出力方針
- setup (準備姿勢) / execution (動作手順) / breathing (呼吸) / mistakes (よくある間違い) /
  tips (コツ) の5区分、各3〜6項目の箇条書き。
- 1項目 = 1つの具体的な動作・注意点。「正しいフォームで行う」のような曖昧な一般論は禁止。
- 関節角度・可動域 (深さ/伸展度)・目線・重心・呼吸のタイミング・よくある代償動作
  (腰が反る/膝が内に入る等) を、体の部位と動きで具体的に書く。
- 日本語。専門用語には簡単な補足を添える。

# 安全性 (重要)
- 一般的な運動フォームの助言に留め、医療アドバイス・診断・治療の提案はしない
  (このアプリは医療機器ではない)。
- 利用者の既往・注意点: {injury_notes}
  該当する動作パターンの種目では、上記に配慮した安全なフォーム・可動域の目安を
  mistakes または tips に必ず反映する。
"""


def _system_prompt() -> str:
    settings = get_settings()
    notes = "; ".join(settings.user_injury_notes) if settings.user_injury_notes else "特になし"
    return _SYSTEM_TEMPLATE.format(injury_notes=notes)


def _valid_steps(raw: Any) -> dict[str, list[str]] | None:
    """tool_use の input を検証。取れた区分は活かし、全滅時のみ None。

    max_tokens 打ち切り等で一部区分が欠けても、埋まった区分は捨てない
    (欠けた区分は空リストで補完)。最低1区分に中身があれば成功とみなす。
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, list[str]] = {}
    for key in _STEP_KEYS:
        items = raw.get(key)
        if isinstance(items, list):
            out[key] = [str(x).strip() for x in items if str(x).strip()]
        else:
            out[key] = []  # 欠損区分は空で補完 (打ち切りに強くする)
    # 全区分が空なら実質失敗扱い (最低1区分は中身があること)
    if not any(out.values()):
        return None
    return out


async def _call_llm(name: str, *, model: str, api_key: str) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        # 5区分×3〜6項目の日本語を出し切る余裕を持たせる (1500 だと mistakes/tips が
        # max_tokens で欠落し、フォームガイドが不完全になっていた)。
        max_tokens=3000,
        system=_system_prompt(),
        messages=[{
            "role": "user",
            "content": f"種目: {name}\nこの種目の詳しいステップ式フォームガイドを提出してください。",
        }],
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "submit_exercise_guide"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input or {})
    return {}


# テストはこれを差し替える (ネットワーク非依存)。
_call = _call_llm


async def generate_guide(name: str) -> dict[str, Any] | None:
    """LLM でフォームガイドを生成。api_key 未設定/生成失敗 (全区分空) 時は None。

    tool_use が全区分空なら1回だけ再試行。それでも中身が無ければ None を返す
    (呼び出し元は保存せず 503。空をキャッシュに焼き付けない)。
    """
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        return None
    try:
        raw = await _call(name, model=settings.llm_model, api_key=api_key)
    except Exception:
        return None
    steps = _valid_steps(raw)
    if steps is None:
        try:
            raw2 = await _call(name, model=settings.llm_model, api_key=api_key)
        except Exception:
            return None
        steps = _valid_steps(raw2)
    if steps is None:
        return None
    return {"name_ja": name, "steps": steps, "model": settings.llm_model}

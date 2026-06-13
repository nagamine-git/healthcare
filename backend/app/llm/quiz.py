"""The Book 章の口頭試問 (Socratic oral exam)。

「説明できた」を構造的に担保するための対話試験。学習科学の retrieval practice /
self-explanation / 教えることによる学習 (protégé 効果) を狙う — 読んだだけの
「わかったつもり」を試験官 Claude が掘り下げて暴き、自分の言葉で説明させる。

会話履歴はフロント保持の単発セッション。サーバはステートレスに 1 ターンずつ採点。
合格 (submit_verdict passed=true) と判断したら、API 層が章の全節 explained を立てる。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.scoring.learning import CURRICULUM, SECTIONS

# 試験官の人格。掘り下げ・誤解の摘発・足場かけ・甘くしない採点を指示する。
_SYSTEM_TEMPLATE = """\
あなたは Rust の熟練メンターで、The Rust Programming Language (The Book) の口頭試問官です。
今回の試問範囲は **第{chapter}章「{title}」** です。
この章の節構成: {sections}
{note}

# 目的
学習者が「読んだだけのわかったつもり」ではなく、この章の核心を**自分の言葉で説明できる**かを見極める。
これは retrieval practice (想起練習) — 学習者に思い出させ、組み立てさせることで定着させるのが狙い。

# 進め方 (1 ターン 1 問、短く)
- まず開いた質問で、章の核心概念を自分の言葉で説明してもらう。
- 説明が曖昧・丸暗記・表面的なら、「なぜ?」「例えば○○のときは?」「それだと△△は破綻しない?」と
  1 問ずつ掘り下げる (elaborative interrogation)。境界・反例・典型的な落とし穴を突く。
- 学習者が詰まったら、答えを教えず**小さなヒントで足場をかけて**引き出す。
- 日本語。1 回の発話は 2〜4 文程度に抑え、一度に複数を問わない。コードは必要なら短く。
- 励ましつつも甘くしない。「なんとなく合ってそう」では通さない。

# 採点 (submit_verdict ツール)
- 核心を自分の言葉で説明でき、主要な誤解が無いと**確信できたら** submit_verdict(passed=true)。
  feedback には、良かった点と、補強するとさらに良い 1 点を簡潔に。
- まだ判断材料が足りない/誤解が残るなら、ツールを呼ばず**次の質問を返す**。
- 数ターン掘っても核心の誤解が解けない・説明できない場合のみ submit_verdict(passed=false)。
  ただし即落とさず最低 3〜4 往復は粘る。落とす時も feedback で「次にどの節を読み直すべきか」を示す。
"""

VERDICT_TOOL: dict[str, Any] = {
    "name": "submit_verdict",
    "description": (
        "口頭試問の合否を確定する。学習者がこの章の核心を自分の言葉で説明でき主要な誤解が"
        "無いと確信できた時に passed=true。説明できない/誤解が解けない時のみ passed=false。"
        "まだ判断できない間はこのツールを呼ばず質問を続けること。"
    ),
    "input_schema": {
        "type": "object",
        "required": ["passed", "feedback"],
        "properties": {
            "passed": {"type": "boolean", "description": "合格なら true。"},
            "feedback": {
                "type": "string",
                "maxLength": 400,
                "description": "日本語の講評。合格なら良かった点+補強点1つ。不合格なら読み直すべき節を示す。",
            },
        },
    },
}

_OPENING = "準備OKです。試問を始めてください。"


async def _anthropic_completion(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> dict[str, Any]:
    """Anthropic を tool_choice=auto で呼び、{text, verdict} に正規化して返す。"""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=1200,
        system=system,
        messages=messages,
        tools=[VERDICT_TOOL],
    )
    text_parts: list[str] = []
    verdict: dict[str, Any] | None = None
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "tool_use" and getattr(block, "name", "") == "submit_verdict":
            inp = block.input
            if isinstance(inp, dict):
                verdict = inp
        elif btype == "text":
            text_parts.append(getattr(block, "text", ""))
    return {"text": " ".join(t for t in text_parts if t).strip(), "verdict": verdict}


# テストはこれを差し替える (ネットワーク非依存にするため)。
_completion = _anthropic_completion


async def quiz_turn(chapter: int, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """口頭試問の 1 ターン。{reply, verdict:{decided,passed,feedback}} を返す。

    messages が空なら試験官が最初の質問から始める。
    """
    info = next((c for c in CURRICULUM if c["chapter"] == chapter), None)
    if info is None:
        raise ValueError(f"unknown chapter: {chapter}")

    secs = SECTIONS.get(chapter, [])
    sections_str = " / ".join(f"{sid} {title}" for sid, title in secs) or "(節なし)"
    note = f"章の注意点: {info['note']}" if info.get("note") else ""
    system = [{
        "type": "text",
        "text": _SYSTEM_TEMPLATE.format(
            chapter=chapter, title=info["title"], sections=sections_str, note=note
        ),
    }]

    convo = list(messages) if messages else [{"role": "user", "content": _OPENING}]

    settings = get_settings()
    out = await _completion(
        system, convo, model=settings.llm_model, api_key=settings.anthropic_api_key or ""
    )

    verdict = out.get("verdict")
    if isinstance(verdict, dict) and "passed" in verdict:
        passed = bool(verdict["passed"])
        feedback = str(verdict.get("feedback") or "")
        return {
            "reply": feedback or out.get("text") or "",
            "verdict": {"decided": True, "passed": passed, "feedback": feedback},
        }
    return {"reply": out.get("text") or "", "verdict": {"decided": False, "passed": None, "feedback": None}}

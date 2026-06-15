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

# 採点 (毎ターン submit_assessment を必ず呼ぶ)
毎ターン、直前の回答までを踏まえて理解度を 0〜100 で更新する。校正基準:
- 0〜30: 読んだだけ/用語の丸暗記/核心を自分の言葉にできない。
- 31〜55: 核心の輪郭は言えるが曖昧・部分的。なぜそうなるかが弱い。
- 56〜79: 核心を自分の言葉で説明でき、簡単な例も出せる。ただし境界/反例/落とし穴に穴。
- 80〜100: 核心を正確に説明し、なぜを述べ、反例や境界条件も外さない。主要な誤解なし。
甘くしない。最初は低めから始め、根拠が示されるたびに上げ、誤解が露呈したら下げる。
80 以上で「クリア」(バックエンドが自動判定) なので、確信なく 80 を付けない。

next_question:
- 80 未満なら、いま最も弱い部分 (なぜ/反例/境界) を突く次の質問を 1 つ入れる (2〜4文、日本語、ヒントで足場)。
- 80 以上に達したと判断したら next_question は空文字。comment に良かった点+補強点1つを簡潔に。
"""

ASSESS_TOOL: dict[str, Any] = {
    "name": "submit_assessment",
    "description": (
        "毎ターン、現時点の理解度 (0-100) と次の質問を提出する。理解度は校正された推定で、"
        "甘く付けない。80 未満なら next_question で最も弱い部分を掘る。"
        "80 以上に達したと判断したら next_question は空にし comment に講評を書く。"
    ),
    "input_schema": {
        "type": "object",
        "required": ["understanding", "next_question", "comment"],
        "properties": {
            "understanding": {
                "type": "integer", "minimum": 0, "maximum": 100,
                "description": "現時点の理解度 (0-100)。校正基準に従い甘く付けない。",
            },
            "next_question": {
                "type": "string", "maxLength": 500,
                "description": "次の質問 (日本語2-4文)。80以上に達したと判断したら空文字。",
            },
            "comment": {
                "type": "string", "maxLength": 300,
                "description": "短い講評/フィードバック (任意、日本語)。クリア時は良かった点+補強点1つ。",
            },
        },
    },
}

CLEAR_THRESHOLD = 80  # この理解度以上でクリア (説明できた を付与)
_OPENING = "準備OKです。試問を始めてください。"


async def _anthropic_completion(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> dict[str, Any]:
    """Anthropic を submit_assessment 強制で呼び、{understanding, next_question, comment} を返す。"""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=1200,
        system=system,
        messages=messages,
        tools=[ASSESS_TOOL],
        tool_choice={"type": "tool", "name": "submit_assessment"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_assessment":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return {}


# テストはこれを差し替える (ネットワーク非依存にするため)。
_completion = _anthropic_completion


async def quiz_turn(chapter: int, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """口頭試問の 1 ターン。理解度%を更新し {understanding, reply, cleared, comment} を返す。

    messages が空なら試験官が最初の質問から始める。理解度 >= CLEAR_THRESHOLD でクリア。
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

    understanding = int(out.get("understanding") or 0)
    understanding = max(0, min(100, understanding))
    next_q = str(out.get("next_question") or "").strip()
    comment = str(out.get("comment") or "").strip()
    cleared = understanding >= CLEAR_THRESHOLD
    # クリア時は講評を、未クリア時は次の質問を表示
    reply = (comment or "理解度が基準に達しました。") if cleared else (next_q or comment)
    return {
        "understanding": understanding,
        "threshold": CLEAR_THRESHOLD,
        "cleared": cleared,
        "comment": comment,
        "reply": reply,
    }

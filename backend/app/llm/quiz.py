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
80 以上が「正解」相当 (得点になる) なので、確信なく 80 を付けない。

next_question:
- **毎ターン必ず次の質問を 1 つ出す** (2〜4文、日本語、詰まっていればヒントで足場)。
- ある観点が十分に説明できたら、同じ問いを繰り返さず**別の観点・別の節**へ移って理解を広げる。
- 合否やクリアは宣言しない (それはシステムが得点で判定する)。comment には直前の回答への短い講評を書く。
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

# クリア後の復習チューター。採点せず、苦手分野を噛み砕いて解説する。
_TUTOR_TEMPLATE = """\
あなたは Rust の親切なメンターで、The Rust Programming Language (The Book) の
**第{chapter}章「{title}」** の復習を手伝います。
この章の節構成: {sections}
{note}

学習者は直前の口頭試問に合格しました。これまでの対話の流れから、学習者が
**詰まった所・曖昧だった所**が見えているはずです。
ここからは試験ではありません。**採点しない復習タイム**です。

# 進め方
- 学習者の質問に、わかりやすく丁寧に答える。「要点 → なぜそうなるか → 具体例」の順で。
- 試問で弱かった部分は、聞かれていなくても噛み砕いて補強してよい。
- コードは短い Rust スニペットで示す。比喩や対比での説明も歓迎。
- 日本語。Markdown を積極的に使う (`インラインコード`、コードブロック、箇条書き、**太字**、見出し)。
- 冗長になりすぎず、相手の理解度に合わせて段階的に。深掘りは相手の反応を見てから。
"""

CLEAR_THRESHOLD = 80  # この理解度以上でクリア (説明できた を付与)
_OPENING = "準備OKです。試問を始めてください。"


# 選択式 (4択/2択) の問題を作る試験官。recognition 課題なので配点は低い (API 側で管理)。
_CHOICE_TEMPLATE = """\
あなたは Rust の熟練メンターで、The Rust Programming Language (The Book) の出題者です。
出題範囲は **第{chapter}章「{title}」** です。
この章の節構成: {sections}
{note}

この章の核心概念を問う **{n}択** の問題を 1 問作成してください。
- 選択肢はちょうど {n} 個。正解はそのうち 1 つだけ。
- 誤答 (distractor) は「ありがちな誤解」を突く、もっともらしいものにする (明らかな出鱈目は不可)。
- 概念理解を問う (単なる構文の暗記や些末な事実は避ける)。コードを使うなら短く。
- これまでの出題と内容が**重複しない**ようにする (会話履歴を参照)。
- 日本語。explanation は「なぜその答えか + 主要な誤答がなぜ違うか」を 2〜4 文で簡潔に。
必ず generate_choice_question ツールを呼んで返すこと。
"""

CHOICE_TOOL: dict[str, Any] = {
    "name": "generate_choice_question",
    "description": "選択式問題を 1 問生成する。options はちょうど指定数、正解は 1 つ。",
    "input_schema": {
        "type": "object",
        "required": ["question", "options", "correct_index", "explanation"],
        "properties": {
            "question": {"type": "string", "maxLength": 500, "description": "設問文 (日本語)。"},
            "options": {
                "type": "array",
                "items": {"type": "string", "maxLength": 200},
                "description": "選択肢 (日本語)。ちょうど指定数。",
            },
            "correct_index": {
                "type": "integer", "minimum": 0,
                "description": "options のうち正解の 0 始まり index。",
            },
            "explanation": {
                "type": "string", "maxLength": 400,
                "description": "なぜその答えか + 主要な誤答がなぜ違うか (日本語2-4文)。",
            },
        },
    },
}


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


async def _anthropic_text(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> str:
    """ツール強制なしの素のテキスト補完。復習チューターの自由応答に使う。"""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=1500,
        system=system,
        messages=messages,
    )
    parts = [
        block.text
        for block in resp.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts).strip()


async def _anthropic_choice(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> dict[str, Any]:
    """Anthropic を generate_choice_question 強制で呼び、その input を返す。"""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=1000,
        system=system,
        messages=messages,
        tools=[CHOICE_TOOL],
        tool_choice={"type": "tool", "name": "generate_choice_question"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "generate_choice_question":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return {}


# テストはこれらを差し替える (ネットワーク非依存にするため)。
_completion = _anthropic_completion
_tutor_completion = _anthropic_text
_choice_completion = _anthropic_choice


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
    # 章クリアの判定は API 層が累計得点で行う。試験官は毎ターン次の質問を出すだけ。
    reply = next_q or comment or "もう少し掘り下げてみましょう。続けてください。"
    return {
        "understanding": understanding,
        "threshold": CLEAR_THRESHOLD,
        "comment": comment,
        "reply": reply,
    }


def _chapter_system(chapter: int, template: str) -> list[dict[str, Any]]:
    """章情報を埋めたシステムプロンプトを組み立てる。"""
    info = next((c for c in CURRICULUM if c["chapter"] == chapter), None)
    if info is None:
        raise ValueError(f"unknown chapter: {chapter}")
    secs = SECTIONS.get(chapter, [])
    sections_str = " / ".join(f"{sid} {title}" for sid, title in secs) or "(節なし)"
    note = f"章の注意点: {info['note']}" if info.get("note") else ""
    return [{
        "type": "text",
        "text": template.format(
            chapter=chapter, title=info["title"], sections=sections_str, note=note
        ),
    }]


async def tutor_turn(chapter: int, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """クリア後の復習チューターの 1 ターン。採点せず {reply} を返す。

    messages にはこれまでの口頭試問のやりとりも含まれるため、チューターは
    学習者が弱かった部分を踏まえて解説できる。
    """
    system = _chapter_system(chapter, _TUTOR_TEMPLATE)
    convo = list(messages) if messages else [{"role": "user", "content": "この章で復習したいことがあります。"}]

    settings = get_settings()
    reply = await _tutor_completion(
        system, convo, model=settings.llm_model, api_key=settings.anthropic_api_key or ""
    )
    return {"reply": reply or "(うまく答えられませんでした。もう一度聞いてください)", "review": True}


async def choice_question(
    chapter: int, messages: list[dict[str, Any]], n: int
) -> dict[str, Any]:
    """選択式 (n 択) の問題を 1 問生成して返す。

    Returns: ``{question, options: [str]*n, correct_index, explanation}``。
    LLM が壊れた出力 (選択肢数の不一致・index 範囲外) を返した場合は補正する。
    """
    info = next((c for c in CURRICULUM if c["chapter"] == chapter), None)
    if info is None:
        raise ValueError(f"unknown chapter: {chapter}")
    if n not in (2, 4):
        raise ValueError(f"unsupported choice count: {n}")

    secs = SECTIONS.get(chapter, [])
    sections_str = " / ".join(f"{sid} {title}" for sid, title in secs) or "(節なし)"
    note = f"章の注意点: {info['note']}" if info.get("note") else ""
    system = [{
        "type": "text",
        "text": _CHOICE_TEMPLATE.format(
            chapter=chapter, title=info["title"], sections=sections_str, note=note, n=n
        ),
    }]
    convo = list(messages) if messages else [{"role": "user", "content": f"{n}択の問題を1問出してください。"}]

    settings = get_settings()
    out = await _choice_completion(
        system, convo, model=settings.llm_model, api_key=settings.anthropic_api_key or ""
    )

    question = str(out.get("question") or "").strip()
    options = [str(o).strip() for o in (out.get("options") or []) if str(o).strip()]
    explanation = str(out.get("explanation") or "").strip()
    correct_index = int(out.get("correct_index") or 0)

    if not question or len(options) < 2:
        raise ValueError("invalid choice question from LLM")
    # n に丸める (多すぎたら切り、少なすぎたらそのまま使う)。index を範囲内へ。
    if len(options) > n:
        options = options[:n]
    correct_index = max(0, min(correct_index, len(options) - 1))

    return {
        "question": question,
        "options": options,
        "correct_index": correct_index,
        "explanation": explanation,
    }

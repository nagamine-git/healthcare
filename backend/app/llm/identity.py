"""Compass (価値観 × マインドセット) の LLM 呼び出し。

quiz.py と同じ思想: 会話履歴はフロント保持の単発セッション、サーバはステートレスに
1 ターンずつ採点。全ツールは tool_choice 強制で構造化出力を得る。テストは末尾の
_*_completion 差し替え点でネットワーク非依存にできる。

提供する 4 機能:
- sjt_turn: 状況判断テスト (SJT) を 1 ターン進め、次元別の現在地 (0-100) を更新する。
- infer_decision_log: 意思決定ログ短文を次元 × 信号 (-1..+1) に紐づける。
- tag_media_dimensions: 作品が「効く次元」を確信度付きで推定する。
- reflect_to_intention: 視聴後の内省対話 → if-then の小さな実行意図を 1 つ生成する。
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.scoring.identity.dimensions import DIMENSIONS


def _dim_reference() -> str:
    """全次元を LLM 向けの一覧文字列にする (id・名前・層・見分けポイント)。"""
    lines = []
    for d in DIMENSIONS:
        lines.append(f"- {d.id} ({d.name_ja} / {d.layer}): {d.sjt_focus}")
    return "\n".join(lines)


def _cached_system(text: str) -> list[dict[str, Any]]:
    """system ブロックに prompt cache (ephemeral) を付ける。

    tools + system の前置きがキャッシュされ、5 分 TTL 内に同一前置きで再呼び出し
    されると入力課金が大幅に下がる。複数ターン対話 (SJT/内省) や、数秒で連続する
    タグ付けループのように「同じ system が短時間に反復する」箇所だけに使う
    (単発呼び出しに付けると初回キャッシュ書き込みが割高になり逆効果のため)。
    出力・振る舞いは一切変わらない (完全ロスレス)。
    """
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


# ===========================================================================
# 1. SJT (状況判断テスト)
# ===========================================================================

_SJT_SYSTEM_TEMPLATE = """\
あなたは組織心理学と起業家認知の専門家で、利用者の「価値観 × マインドセット」の現在地を
**状況判断テスト (SJT)** で測定します。

# なぜ SJT か
利用者は「サラリーマンマインドが抜けない」と自覚していますが、それは**自分で気づけない盲点**です。
「あなたは主体的ですか?」と直接聞くと社会的望ましさバイアスで過大評価されます。だから
**具体的な状況で実際にどう動くかの選択**から推定します。自己申告の美辞麗句は割り引き、
選んだ行動と理由づけ (帰属の仕方・最初の一手) から冷静に評価してください。

# 測定する次元 (id: 名前 / 層: 見分けポイント)
{dim_reference}

# 進め方 (1 ターン 1 シナリオ)
- 毎ターン、現実的で具体的な状況を 1 つ提示し、3〜4 個の選択肢を出す。
  選択肢は「ありがちな従業員的反応」と「起業家的反応」を、どちらも妥当に見えるよう混ぜる
  (正解が露骨に分からないように)。
- 1 つのシナリオで複数次元を同時に観察してよい (効率重視。全 17 次元を無駄なく覆う)。
- 利用者の選択と理由を受けて、関係する次元のスコアを更新する。
  スコア 0-100 は「その次元の起業家寄りの極をどれだけ示すか」(高いほど founder 的)。
  根拠が薄い段階では confidence を低くし、選択が一貫したら上げる。
- 日本語。シナリオ本文は 2〜4 文。説教しない。

# 出力 (毎ターン submit_sjt を必ず呼ぶ)
- assessed: これまでに観察できた全次元の累積スコア (毎ターン全件を返す。確信が増したら上書き)。
- next_scenario: 次の状況と選択肢。まだ十分に測れていない次元を優先して突く。
- done: 全 17 次元を十分な確信で測り終えたら true、その時 next_scenario は空。
- comment: 直前の選択への短い所見 (任意、説教しない)。
"""

SJT_TOOL: dict[str, Any] = {
    "name": "submit_sjt",
    "description": (
        "状況判断テストの 1 ターン。assessed に観察済み全次元の累積スコアを返し、"
        "next_scenario で次の状況を出す。全次元を測り終えたら done=true。"
    ),
    "input_schema": {
        "type": "object",
        "required": ["assessed", "next_scenario", "done"],
        "properties": {
            "assessed": {
                "type": "array",
                "description": "観察できた全次元の累積スコア (毎ターン全件)。",
                "items": {
                    "type": "object",
                    "required": ["dimension_id", "score", "confidence"],
                    "properties": {
                        "dimension_id": {"type": "string"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            "next_scenario": {
                "type": "object",
                "description": "次の状況判断シナリオ。done=true なら situation を空に。",
                "properties": {
                    "situation": {"type": "string", "maxLength": 600},
                    "options": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 200},
                    },
                },
            },
            "done": {"type": "boolean", "description": "全次元を十分測れたら true。"},
            "comment": {"type": "string", "maxLength": 300},
        },
    },
}

_SJT_OPENING = "準備OKです。最初の状況を出してください。"


async def _anthropic_sjt(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=2000,
        system=system,
        messages=messages,
        tools=[SJT_TOOL],
        tool_choice={"type": "tool", "name": "submit_sjt"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_sjt":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return {}


# ===========================================================================
# 2. 意思決定ログの次元推定
# ===========================================================================

_DECISION_SYSTEM = """\
あなたは起業家認知の専門家です。利用者が書いた「今日こういう場面でこう動いた」という短い
意思決定ログを読み、それが下記のどの次元をどの向きに示すかを推定します。

# 次元 (id: 名前 / 層: 見分けポイント)
{dim_reference}

# 指示
- ログが示す次元だけを挙げる (無関係な次元は出さない。1〜4 個程度)。
- signal は -1.0〜+1.0。+1 はその次元の起業家寄りの極を強く示す行動、-1 は従業員寄り
  (受け身・外部帰属・先延ばし・前例踏襲) を強く示す行動。中間は程度に応じて。
- 自己正当化や美化は割り引く。実際に取った行動で判断する。
- rationale は日本語 1 文で根拠を簡潔に。
必ず submit_decision_signals ツールで返すこと。
"""

DECISION_TOOL: dict[str, Any] = {
    "name": "submit_decision_signals",
    "description": "意思決定ログから次元別の信号 (-1..+1) を抽出する。",
    "input_schema": {
        "type": "object",
        "required": ["signals"],
        "properties": {
            "signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["dimension_id", "signal", "rationale"],
                    "properties": {
                        "dimension_id": {"type": "string"},
                        "signal": {"type": "number", "minimum": -1, "maximum": 1},
                        "rationale": {"type": "string", "maxLength": 200},
                    },
                },
            },
        },
    },
}


async def _anthropic_decision(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=1000,
        system=system,
        messages=messages,
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "submit_decision_signals"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_decision_signals":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return {}


# ===========================================================================
# 3. 作品の次元タグ付け
# ===========================================================================

_TAG_SYSTEM = """\
あなたは物語と人格形成の専門家です。与えられた作品 (映画/TV/マンガ/本) が、下記の次元の
うちどれを育てる効果があるかを、登場人物の生き方・テーマ・読後に促される態度から推定します。

# 次元 (id: 名前 / 層: 見分けポイント)
{dim_reference}

# 指示
- その作品が明確に効く次元だけを挙げる (1〜5 個)。薄い関連は出さない。
- confidence は 0〜1。作品の中心テーマに直結するほど高く。
- 観た/読んだ後に「その次元の起業家寄りの極」へ動機づけられるかで判断する。
必ず submit_media_tags ツールで返すこと。
"""

TAG_TOOL: dict[str, Any] = {
    "name": "submit_media_tags",
    "description": "作品が育てる次元を確信度付きで返す。",
    "input_schema": {
        "type": "object",
        "required": ["tags"],
        "properties": {
            "tags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["dimension_id", "confidence"],
                    "properties": {
                        "dimension_id": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
        },
    },
}


async def _anthropic_tag(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=800,
        system=system,
        messages=messages,
        tools=[TAG_TOOL],
        tool_choice={"type": "tool", "name": "submit_media_tags"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_media_tags":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return {}


# ===========================================================================
# 4. 視聴後の内省 → 実行意図
# ===========================================================================

_REFLECT_SYSTEM = """\
あなたは行動変容コーチ (ACT と実装意図の専門家) です。利用者がある作品を観終えた後の
内省を手伝い、最後に **if-then の小さな実行意図** を 1 つだけ作ります。

# 前提となる科学
作品を観るだけでは行動は変わりません。効くのは (1) 登場人物への同一化で自己効力感が上がり、
(2) 内省し、(3) **実行意図 (「もし X なら Y する」) の小さな具体行動**に変換したときだけです
(Narrative Transportation / Bandura のモデリング / Gollwitzer の implementation intentions)。
「欠陥を直す」ではなく「自分が選んだ価値に沿って一歩進む」と前向きに枠づけてください (ACT)。

# 対象次元
この作品が育てうる次元: {target_dimensions}

# 進め方
- まず短い問いで、作品の中で心が動いた場面と、それが自分の {target_dimensions} とどう繋がるかを
  引き出す (1〜2 ターン)。説教しない。日本語。
- 機が熟したら submit_reflection を呼ぶ。intention は今日〜数日で実行できる**極小の if-then**
  (例: 「もし明日の朝会で言いたい改善案が浮かんだら、その場で一言だけ口に出す」)。
  大きすぎる決意は不可。intention_dimension_id は最も効く 1 次元。
- まだ内省が浅い段階では intention を空にし、next_question で掘り下げる。
"""

REFLECT_TOOL: dict[str, Any] = {
    "name": "submit_reflection",
    "description": (
        "内省の 1 ターン。まだ浅ければ next_question で掘り、機が熟したら intention に "
        "if-then の極小実行意図を入れる。"
    ),
    "input_schema": {
        "type": "object",
        "required": ["next_question", "intention", "intention_dimension_id", "comment"],
        "properties": {
            "next_question": {
                "type": "string", "maxLength": 400,
                "description": "次の問い (日本語)。実行意図が固まったら空文字。",
            },
            "intention": {
                "type": "string", "maxLength": 300,
                "description": "if-then の極小実行意図 (日本語)。まだ早ければ空文字。",
            },
            "intention_dimension_id": {
                "type": "string", "description": "実行意図が最も効く次元 id (intention が空なら空)。",
            },
            "comment": {"type": "string", "maxLength": 300},
        },
    },
}


async def _anthropic_reflect(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=1200,
        system=system,
        messages=messages,
        tools=[REFLECT_TOOL],
        tool_choice={"type": "tool", "name": "submit_reflection"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_reflection":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return {}


# ===========================================================================
# 5. リスト外の新規作品提案
# ===========================================================================

_SUGGEST_SYSTEM = """\
あなたは物語と人格形成の専門家です。利用者の「伸びしろが大きい次元」を強く育てる作品
(映画/TV/マンガ/本) を、利用者がまだ持っていないものから提案します。

# 伸ばしたい次元 (id: 名前)
{weak_dims}

# 指示
- 実在し、入手しやすい著名作を挙げる (架空の作品・うろ覚えのタイトルは禁止)。
- すでに利用者のリストにある作品 (下記) は提案しない。
- **本(book)を中心に厚めに**提案する(利用者は読書家)。映画/ドラマ/マンガも混ぜてよいが、
  全体の半数以上は本にする。kind は内容に合った正しい種別を付ける。
- **利用者の読書の好み(下記)に強く寄せる**: 好きな著者の他作・同系統の良書、よく読む分野を
  優先。**言語傾向も尊重**し、和書(日本語の本)を多く読む利用者には**和書を多め**に、その分野
  (ビジネス/自己啓発/日本人作家の小説 等)で実在する具体的な良書を挙げる。タイトルは
  原語表記でよい(和書は日本語タイトル)。好みが空のときだけ汎用の名作でよい。
- 各提案に、最も効く dimension_id を 1 つと、なぜ効くかの理由 (日本語1-2文) を付ける。
- 伸びしろ次元を満たしつつ、起業家マインド (founder) の形成に資する骨太な作品を優先する。
- **多様性**: 同じ著者やシリーズに偏らせず、幅を持たせる。
必ず submit_suggestions ツールで返すこと。

# 利用者の読書の好み
{taste}

# すでにリストにある作品 (重複させない)
{avoid}
"""

SUGGEST_TOOL: dict[str, Any] = {
    "name": "submit_suggestions",
    "description": "リスト外の新規作品を、効く次元と理由付きで提案する。",
    "input_schema": {
        "type": "object",
        "required": ["suggestions"],
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "kind", "dimension_id", "reason"],
                    "properties": {
                        "title": {"type": "string", "maxLength": 200},
                        "kind": {"type": "string", "enum": ["film", "tv", "manga", "book"]},
                        "year": {"type": "integer"},
                        "dimension_id": {"type": "string"},
                        "reason": {"type": "string", "maxLength": 200},
                    },
                },
            },
        },
    },
}


async def _anthropic_suggest(
    system: list[dict[str, Any]], messages: list[dict[str, Any]], *, model: str, api_key: str
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=2800,
        system=system,
        messages=messages,
        tools=[SUGGEST_TOOL],
        tool_choice={"type": "tool", "name": "submit_suggestions"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_suggestions":
            inp = block.input
            if isinstance(inp, dict):
                return inp
    return {}


# テストはこれらを差し替える (ネットワーク非依存)。
_sjt_completion = _anthropic_sjt
_decision_completion = _anthropic_decision
_tag_completion = _anthropic_tag
_reflect_completion = _anthropic_reflect
_suggest_completion = _anthropic_suggest


def _valid_dim_ids(items: list[dict[str, Any]], key: str = "dimension_id") -> list[dict[str, Any]]:
    """未知の dimension_id を持つ要素を捨てる (LLM の取りこぼし対策)。"""
    from app.scoring.identity.dimensions import BY_ID

    return [it for it in items if isinstance(it, dict) and it.get(key) in BY_ID]


async def sjt_turn(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """SJT を 1 ターン進める。{assessed, next_scenario, done, comment} を返す。"""
    settings = get_settings()
    system = _cached_system(_SJT_SYSTEM_TEMPLATE.format(dim_reference=_dim_reference()))
    convo = list(messages) if messages else [{"role": "user", "content": _SJT_OPENING}]
    out = await _sjt_completion(
        system, convo, model=settings.llm_model, api_key=settings.anthropic_api_key or ""
    )
    assessed = _valid_dim_ids(list(out.get("assessed") or []))
    scenario = out.get("next_scenario") or {}
    if not isinstance(scenario, dict):
        scenario = {}
    return {
        "assessed": assessed,
        "next_scenario": {
            "situation": str(scenario.get("situation") or "").strip(),
            "options": [str(o).strip() for o in (scenario.get("options") or []) if str(o).strip()],
        },
        "done": bool(out.get("done")),
        "comment": str(out.get("comment") or "").strip(),
    }


async def infer_decision_log(text: str) -> list[dict[str, Any]]:
    """意思決定ログ短文 → [{dimension_id, signal, rationale}]。"""
    settings = get_settings()
    system = [{"type": "text", "text": _DECISION_SYSTEM.format(dim_reference=_dim_reference())}]
    convo = [{"role": "user", "content": text}]
    out = await _decision_completion(
        system, convo, model=settings.llm_model, api_key=settings.anthropic_api_key or ""
    )
    signals = _valid_dim_ids(list(out.get("signals") or []))
    # signal を範囲内に丸める。
    for s in signals:
        s["signal"] = max(-1.0, min(1.0, float(s.get("signal") or 0.0)))
    return signals


async def tag_media_dimensions(
    *, title: str, kind: str, year: int | None, overview: str | None
) -> dict[str, float]:
    """作品 → {dimension_id: confidence}。"""
    settings = get_settings()
    system = _cached_system(_TAG_SYSTEM.format(dim_reference=_dim_reference()))
    desc = f"作品: {title} ({kind}, {year or '年不明'})\n概要: {overview or '(概要なし)'}"
    convo = [{"role": "user", "content": desc}]
    out = await _tag_completion(
        system, convo, model=settings.llm_model, api_key=settings.anthropic_api_key or ""
    )
    tags = _valid_dim_ids(list(out.get("tags") or []))
    return {t["dimension_id"]: max(0.0, min(1.0, float(t.get("confidence") or 0.0))) for t in tags}


async def reflect_to_intention(
    *, title: str, target_dimensions: list[str], messages: list[dict[str, Any]]
) -> dict[str, Any]:
    """視聴後の内省 1 ターン。{next_question, intention, intention_dimension_id, comment}。"""
    from app.scoring.identity.dimensions import BY_ID

    settings = get_settings()
    names = ", ".join(BY_ID[d].name_ja for d in target_dimensions if d in BY_ID) or "(未指定)"
    system = _cached_system(_REFLECT_SYSTEM.format(target_dimensions=names))
    opening = f"「{title}」を観終えました。内省を手伝ってください。"
    convo = list(messages) if messages else [{"role": "user", "content": opening}]
    out = await _reflect_completion(
        system, convo, model=settings.llm_model, api_key=settings.anthropic_api_key or ""
    )
    intention = str(out.get("intention") or "").strip()
    dim_id = str(out.get("intention_dimension_id") or "").strip()
    if dim_id not in BY_ID:
        dim_id = ""
    return {
        "next_question": str(out.get("next_question") or "").strip(),
        "intention": intention,
        "intention_dimension_id": dim_id,
        "comment": str(out.get("comment") or "").strip(),
    }


_MATCH_SYSTEM = """\
あなたは書誌の同定の専門家です。利用者の「おすすめ候補(主に英語タイトル)」のうち、
利用者が**既に読んだ蔵書**(和訳・別エディションを含む)と**同一の作品**であるものを特定します。

# 指示
- 言語・翻訳・版の違いを越えて「同じ作品」を一致とみなす(例: "The Lean Startup" =「リーン・スタートアップ」)。
- **確信できる同一作品だけ**を返す(著者やテーマが似ているだけ、シリーズ違いは一致させない)。
- 一致した候補の id を返す。無ければ空。
必ず submit_matches ツールで返すこと。
"""

_MATCH_TOOL: dict[str, Any] = {
    "name": "submit_matches",
    "description": "既読の蔵書と同一だと確信できるおすすめ候補の id を返す。",
    "input_schema": {
        "type": "object",
        "required": ["matched_ids"],
        "properties": {
            "matched_ids": {"type": "array", "items": {"type": "integer"}},
        },
    },
}


async def match_read_titles(candidates: list[dict[str, Any]], read_books: list[str]) -> list[int]:
    """おすすめ候補のうち、既読の蔵書(言語横断)と同一の作品の id を返す。

    candidates: [{id, title, year}] のおすすめ本。read_books: ["Title — Author", ...] の既読本。
    api_key 未設定/失敗時は []。
    """
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key or not candidates or not read_books:
        return []
    cand_str = "\n".join(
        f"- id={c['id']}: {c['title']}" + (f" ({c['year']})" if c.get("year") else "")
        for c in candidates
    )
    read_str = "\n".join(f"- {t}" for t in read_books[:200])
    user = f"# おすすめ候補\n{cand_str}\n\n# 既に読んだ蔵書\n{read_str}"
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=500,
            system=_MATCH_SYSTEM,
            messages=[{"role": "user", "content": user}],
            tools=[_MATCH_TOOL],
            tool_choice={"type": "tool", "name": "submit_matches"},
        )
    except Exception:
        return []
    valid = {c["id"] for c in candidates}
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_matches":
            inp = block.input
            if isinstance(inp, dict):
                return [int(i) for i in inp.get("matched_ids", []) if int(i) in valid]
    return []


async def suggest_new_media(
    *,
    weak_dims: list[tuple[str, str]],
    avoid_titles: list[str],
    n: int = 12,
    taste: str | None = None,
) -> list[dict[str, Any]]:
    """伸びしろの大きい次元向けに、リスト外の新規作品を提案する。

    weak_dims: [(dimension_id, name_ja)] の弱い次元 (上位)。
    avoid_titles: 既にライブラリにある作品名 (重複させない)。
    taste: 利用者の読書の好み(蔵書 CSV 由来)。提案をこれに寄せる。
    返り値: [{title, kind, year, dimension_id, reason}]。
    """
    from app.scoring.identity.dimensions import BY_ID

    settings = get_settings()
    weak_str = "\n".join(f"- {d_id} ({name})" for d_id, name in weak_dims) or "(なし)"
    avoid_str = "\n".join(f"- {t}" for t in avoid_titles[:200]) or "(なし)"
    system = [
        {
            "type": "text",
            "text": _SUGGEST_SYSTEM.format(
                weak_dims=weak_str, avoid=avoid_str, taste=taste or "(未登録)"
            ),
        }
    ]
    convo = [{"role": "user", "content": f"{n} 作品ほど提案してください。"}]
    out = await _suggest_completion(
        system, convo, model=settings.llm_model, api_key=settings.anthropic_api_key or ""
    )
    suggestions = []
    for s in out.get("suggestions") or []:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        dim_id = str(s.get("dimension_id") or "").strip()
        kind = str(s.get("kind") or "film").strip()
        if not title or dim_id not in BY_ID or kind not in ("film", "tv", "manga", "book"):
            continue
        year = s.get("year")
        suggestions.append(
            {
                "title": title,
                "kind": kind,
                "year": int(year) if isinstance(year, int) else None,
                "dimension_id": dim_id,
                "reason": str(s.get("reason") or "").strip(),
            }
        )
    return suggestions

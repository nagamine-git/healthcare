"""価値観 × マインドセットの次元カタログ (DB 非依存の枠組み定数)。

「16personalities (MBTI)」のような再検査信頼性の低い類型ではなく、心理測定学的に
確立した枠組みに接地させる:

- 価値観層: Schwartz の基本価値理論 (Schwartz 1992, 2012)。普遍的な 10 の価値を
  円環状に配置し「変化への開放性 ↔ 保守」「自己高揚 ↔ 自己超越」の 2 軸で整理する。
- マインドセット層: 起業家認知 (employee mindset と founder mindset を分ける研究済みの
  心理次元)。内的統制 (Rotter)、主体性 (Bateman & Crant の Proactive Personality)、
  有効化思考 (Sarasvathy の Effectuation)、リスク・曖昧さ耐性、達成欲求 (McClelland)、
  成長マインドセット (Dweck)、オーナーシップ (bias for action)。

次元定義 (= 全人類共通の枠組み) はここに固定し、「理想プロファイル (どの次元をどこまで
高めたいか)」だけを config / DB に personal target として持つ (achievement.py が
臨床定数を持ち、目標体重等を personal target として分離するのと同じ思想)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Layer = Literal["values", "mindset"]


@dataclass(frozen=True)
class Dimension:
    """1 つの測定次元。

    id: 安定した識別子 (DB / config / LLM 出力で共有する。後方互換のため変更しない)。
    layer: "values" (方向・なぜ) か "mindset" (円能力・どう振る舞うか)。
    name_ja: 表示名。
    description: 高い側が何を意味するか (SJT 生成とギャップ説明の土台)。
    research_basis: 学術的根拠 (説明可能性のため)。
    sjt_focus: SJT (状況判断問題) で何を見分けるかの一言。
    """

    id: str
    layer: Layer
    name_ja: str
    description: str
    research_basis: str
    sjt_focus: str


# --- 価値観層: Schwartz 基本価値 10 (円環順) ---
_VALUES: tuple[Dimension, ...] = (
    Dimension(
        "self_direction", "values", "自律",
        "自分で考え選び、独立して行動・探究することを重視する。",
        "Schwartz 基本価値 (Self-Direction)。変化への開放性の核。",
        "指示待ちか、自分で意思決定して動くか。",
    ),
    Dimension(
        "stimulation", "values", "刺激",
        "新奇さ・挑戦・興奮を求める。",
        "Schwartz (Stimulation)。",
        "安定を選ぶか、新しい挑戦に踏み出すか。",
    ),
    Dimension(
        "hedonism", "values", "快楽",
        "自分の快・楽しみを重視する。",
        "Schwartz (Hedonism)。変化への開放性と自己高揚の境界。",
        "目先の快を取るか、目的のために我慢するか。",
    ),
    Dimension(
        "achievement", "values", "達成",
        "社会的基準に照らした有能さ・成功を重視する。",
        "Schwartz (Achievement)。自己高揚の核。",
        "現状維持で満足するか、成果で示そうとするか。",
    ),
    Dimension(
        "power", "values", "権力・資源",
        "地位・支配・資源のコントロールを重視する。",
        "Schwartz (Power)。",
        "影響力や資源の獲得をどれだけ志向するか。",
    ),
    Dimension(
        "security", "values", "安全",
        "安全・調和・安定 (自他・社会) を重視する。",
        "Schwartz (Security)。保守の核。",
        "不確実性を避けるか、許容して進むか。",
    ),
    Dimension(
        "conformity", "values", "同調",
        "規範・期待からの逸脱を避け、和を保つことを重視する。",
        "Schwartz (Conformity)。保守側。",
        "場の期待に合わせるか、必要なら摩擦を取るか。",
    ),
    Dimension(
        "tradition", "values", "伝統",
        "慣習・文化的伝統を尊重し維持することを重視する。",
        "Schwartz (Tradition)。保守側。",
        "前例を守るか、前例を疑って作り替えるか。",
    ),
    Dimension(
        "benevolence", "values", "善行",
        "身近な人々の幸福を守り高めることを重視する。",
        "Schwartz (Benevolence)。自己超越の核。",
        "自分優先か、近しい人への貢献を優先するか。",
    ),
    Dimension(
        "universalism", "values", "普遍主義",
        "万人・自然の福祉と公正を理解し守ることを重視する。",
        "Schwartz (Universalism)。自己超越側。",
        "内輪を超えた公正・大義をどれだけ志向するか。",
    ),
)

# --- マインドセット層: 起業家認知 ---
_MINDSET: tuple[Dimension, ...] = (
    Dimension(
        "internal_locus", "mindset", "内的統制",
        "結果は運や環境ではなく自分の行動次第だと捉える。",
        "Rotter の Locus of Control。起業家で内的傾向が強い (Rauch & Frese 2007)。",
        "うまくいかない時、外部要因に帰属するか自分の打ち手に帰属するか。",
    ),
    Dimension(
        "proactivity", "mindset", "主体性",
        "機会を先取りし、頼まれる前に動いて環境を変えにいく。",
        "Bateman & Crant の Proactive Personality。",
        "誰かが決めるのを待つか、自分から先に動くか。",
    ),
    Dimension(
        "effectuation", "mindset", "有効化思考",
        "手持ちの資源 (bird-in-hand) から始め、許容可能な損失で賭け、偶然を活かす。",
        "Sarasvathy の Effectuation (causation との対)。",
        "完璧な計画を待つか、今ある手段で小さく始めるか。",
    ),
    Dimension(
        "risk_tolerance", "mindset", "リスク・曖昧さ耐性",
        "不確実・曖昧な状況でも前進でき、計算されたリスクを取れる。",
        "Ambiguity Tolerance / risk propensity 研究。",
        "情報が揃わない時に止まるか、不確実なまま意思決定するか。",
    ),
    Dimension(
        "need_for_achievement", "mindset", "達成欲求",
        "高い基準を自ら課し、難しい目標を達成しようと駆動される。",
        "McClelland の Need for Achievement (nAch)。",
        "楽な道を選ぶか、難度の高い目標に自ら挑むか。",
    ),
    Dimension(
        "growth_mindset", "mindset", "成長マインドセット",
        "能力は努力と学習で伸ばせると捉え、失敗を学習機会と見る。",
        "Dweck の Growth vs Fixed Mindset。",
        "失敗を能力の証明と見るか、学習データと見るか。",
    ),
    Dimension(
        "ownership", "mindset", "オーナーシップ",
        "「自分の仕事ではない」を排し、当事者として結果に責任を負い即座に動く。",
        "Bias for action / extreme ownership。employee mindset の対極。",
        "範囲外として線を引くか、当事者として引き受けて動くか。",
    ),
)

DIMENSIONS: tuple[Dimension, ...] = _VALUES + _MINDSET

# id → Dimension の索引。
BY_ID: dict[str, Dimension] = {d.id: d for d in DIMENSIONS}

VALUE_IDS: tuple[str, ...] = tuple(d.id for d in _VALUES)
MINDSET_IDS: tuple[str, ...] = tuple(d.id for d in _MINDSET)
ALL_IDS: tuple[str, ...] = tuple(d.id for d in DIMENSIONS)


def get_dimension(dim_id: str) -> Dimension | None:
    return BY_ID.get(dim_id)


def dimensions_for_layer(layer: Layer) -> tuple[Dimension, ...]:
    return tuple(d for d in DIMENSIONS if d.layer == layer)

"""ExerciseDB (RapidAPI) から種目デモ GIF を取得する。

方針: あいまいな `/exercises/name/{term}` 部分一致 + 先頭1件採用は、器具違い
(バンド/バーベル種目がダンベル種目としてヒットする等) や動作違いの誤マッチを繰り返し
起こしていた。そこで:

1. `_JA_TO_ID` — training_split.py の全種目は本番プローブで ID を事前確認済み。
   一致すれば実行時検索は行わない (最も確実)。
2. キュレーション対象外の種目は、JA名から器具 (dumbbell/body weight) を推定し、
   `/exercises/equipment/{type}` で **その器具の種目だけ** に絞った上でキーワードの
   トークン重なりでスコアリングする (器具違いの誤マッチを構造的に防ぐ)。
3. どちらも自信が持てない/ユーザーが違うと感じた場合のために `list_candidates` で
   上位候補を返す (フロントの候補ピッカー用)。ユーザーの確定選択は DB 側
   (ExerciseGifOverride) で永続化し、次回以降はそれを最優先する (api/exercise.py)。

剣道素振り/シャドー/ジョグ/タバタ 等、対応する種目が無いものはマップに含めない
→ GIF 無し (None)。誤った画像を出すよりは無い方が良い、という一貫方針。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

# 括弧を除いた日本語種目名 (小文字・空白除去) → ExerciseDB 検索語 (英語)。
# curated_id で当たらない種目のキーワードスコアリングや、後方互換の search_term で使う。
_JA_TO_EN: dict[str, str] = {
    "ダンベルベンチプレス": "dumbbell bench press",
    "ダンベルショルダープレス": "dumbbell seated shoulder press",
    "ダンベルルーマニアンデッドリフト": "dumbbell romanian deadlift",
    "ダンベルrdl": "dumbbell romanian deadlift",
    "ダンベルロー": "dumbbell bent over row",
    "ダンベルゴブレットスクワット": "dumbbell goblet squat",
    "ゴブレットスクワット": "dumbbell goblet squat",
    "ダンベルランジ": "dumbbell lunge",
    "腕立て伏せ": "push-up",
    "プッシュアップ": "push-up",
    "パイクプッシュアップ": "pike-to-cobra push-up",
    "インバーテッドロー": "inverted row",
    "スーパーマン": "superman back extension",
    "自重スクワット": "bodyweight squat",
    "ブルガリアンスクワット": "dumbbell single leg split squat",
    "ブルガリアン": "dumbbell single leg split squat",
    "ピストルスクワット": "single leg squat pistol",
    "ダンベルフライ": "dumbbell fly",
    "サイドレイズ": "dumbbell lateral raise",
    "ダンベルフレンチプレス": "dumbbell standing triceps extension",
    "ダンベルカール": "dumbbell biceps curl",
    "ハンマーカール": "dumbbell hammer curl",
    "ダンベルリアレイズ": "dumbbell rear lateral raise",
    "ダンベルシュラッグ": "dumbbell shrug",
    "カーフレイズ": "dumbbell standing calf raise",
    "ダンベルステップアップ": "dumbbell step up",
    "ダンベルヒップスラスト": "barbell glute bridge two legs on bench",
    "ヒップスラスト": "barbell glute bridge two legs on bench",
    "プランク": "front plank",
    "レッグレイズ": "lying leg raise flat bench",
    "ダンベルサイドベンド": "dumbbell side bend",
    "デッドバグ": "dead bug",
    # HIIT 系 (ExerciseDB にダンベルGIFがある種目に寄せる)
    "ダンベルプッシュプレス": "dumbbell push press",
    "ダンベルスラスター": "dumbbell push press",  # ダンベル版スラスターGIF無し→近い押上げ動作
    "ダンベルクリーン": "dumbbell clean",
    "ダンベルバービー": "dumbbell burpee",
    "バービー": "body weight burpee",  # 静音バーピー(ダンベル無し) は自重版
    "バーピー": "body weight burpee",
    "マウンテンクライマー": "mountain climber",
    "ダンベルスイング": "kettlebell swing",  # ダンベル版GIF無し→動作が近い代替
    "ファーマーズマーチ": "farmers walk",
}

# 事前キュレーション済み ExerciseDB ID (本番プローブ + equipment/instructions 確認済み)。
# search_term のあいまい一致に頼らず、この種目は必ずこの GIF を出す。
_JA_TO_ID: dict[str, str] = {
    "ダンベルベンチプレス": "0289",
    "ダンベルショルダープレス": "0405",
    "ダンベルルーマニアンデッドリフト": "1459",
    "ダンベルrdl": "1459",
    "ダンベルロー": "0292",  # dumbbell one arm bent-over row (「片手」明記に合わせる)
    "ダンベルゴブレットスクワット": "1760",
    "ゴブレットスクワット": "1760",
    "ダンベルランジ": "0336",
    "腕立て伏せ": "0662",
    "プッシュアップ": "0662",
    "パイクプッシュアップ": "3662",  # pike-to-cobra push-up (完全一致無し、最も近い)
    "インバーテッドロー": "0499",
    "自重スクワット": "3533",  # bodyweight squat (旧: dumbbell squat は器具不一致だった)
    "ブルガリアンスクワット": "0410",  # dumbbell single leg split squat
    "ブルガリアン": "0410",
    "ピストルスクワット": "1759",  # single leg squat (pistol) male
    "ダンベルフライ": "0308",
    "サイドレイズ": "0334",  # dumbbell lateral raise (標準形)
    "ダンベルフレンチプレス": "0430",  # dumbbell standing triceps extension (exercise ball不要)
    "ダンベルカール": "0294",
    "ハンマーカール": "0313",
    "ダンベルリアレイズ": "0380",
    "ダンベルシュラッグ": "0406",  # dumbbell shrug (立位・ベンチ角度不要)
    "カーフレイズ": "0417",  # dumbbell standing calf raise
    "ダンベルステップアップ": "0431",
    "ダンベルヒップスラスト": "3562",  # barbell glute bridge two legs on bench
    "ヒップスラスト": "3562",  # (ダンベル版デモが無い → フォーム一致のバーベル版で代替)
    "プランク": "0464",  # front plank with twist (完全一致無し、最も近い)
    "レッグレイズ": "0620",  # lying leg raise flat bench (旧: hanging版はバー前提で器具不一致)
    "ダンベルサイドベンド": "0407",
    "デッドバグ": "0276",
    "ダンベルプッシュプレス": "1700",
    "ダンベルスラスター": "1700",
    "ダンベルクリーン": "0295",
    "ダンベルバービー": "1201",  # dumbbell burpee
    "バービー": "1160",  # 静音バーピー(ダンベル無し) は body weight burpee
    "バーピー": "1160",
    "マウンテンクライマー": "0630",
    "ファーマーズマーチ": "2133",
    # スーパーマン(背面伸展)・ダンベルスイングは ExerciseDB に一致する種目が無いため
    # 意図的に含めない (誤った画像より GIF 無しの方が良い)。
}

# JA名にこれらが含まれれば equipment="body weight" と推定 (それ以外は既定 "dumbbell")。
_BODYWEIGHT_KEYWORDS = (
    "自重", "腕立て", "プッシュアップ", "プランク", "レッグレイズ", "デッドバグ",
    "マウンテンクライマー", "バーピー", "バービー", "ピストルスクワット",
    "インバーテッドロー", "スーパーマン",
)

_WORD_RE = re.compile(r"[a-z]+")


def _base(name: str) -> str:
    n = re.sub(r"[（(].*", "", name)
    return n.replace(" ", "").replace("　", "").strip().lower()


def _longest_key_match(base: str, table: dict[str, str]) -> str | None:
    if base in table:
        return table[base]
    for k in sorted(table, key=len, reverse=True):
        if k in base:
            return table[k]
    return None


def search_term(name: str) -> str | None:
    """日本語種目名 → ExerciseDB 検索語 (キーワードヒント)。マップ外は None。"""
    return _longest_key_match(_base(name), _JA_TO_EN)


def curated_id(name: str) -> str | None:
    """日本語種目名 → 事前キュレーション済み ExerciseDB ID。無ければ None。"""
    return _longest_key_match(_base(name), _JA_TO_ID)


def infer_equipment(name: str) -> str:
    """日本語種目名から ExerciseDB の equipment 値を推定する (既定は "dumbbell")。"""
    base = _base(name)
    if any(kw in base for kw in _BODYWEIGHT_KEYWORDS):
        return "body weight"
    return "dumbbell"


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _score(query: str, candidate_name: str) -> float:
    """query の英単語集合と候補名のトークン重なり率 (0-1、query 側の網羅率)。"""
    q = _words(query)
    c = _words(candidate_name)
    if not q or not c:
        return 0.0
    return len(q & c) / len(q)


def _cache_dir() -> Path:
    d = get_settings().app_data_dir / "exercise_gifs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_equipment_pool(equipment: str) -> list[dict[str, Any]]:
    """equipment 別の全種目リストを取得 (ページング、10件/リクエストが上限)。ディスクに永続キャッシュ。"""
    cache = _cache_dir() / f"equipment_{equipment.replace(' ', '_')}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except (OSError, ValueError):
            pass

    s = get_settings()
    if not s.exercisedb_api_key:
        return []
    headers = {"X-RapidAPI-Key": s.exercisedb_api_key, "X-RapidAPI-Host": s.exercisedb_host}
    items: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=12.0) as client:
            offset = 0
            while offset <= 500:  # 安全弁 (この equipment がこれ以上多いことは想定しない)
                r = client.get(
                    f"https://{s.exercisedb_host}/exercises/equipment/{equipment}",
                    headers=headers, params={"limit": 10, "offset": offset},
                )
                r.raise_for_status()
                batch = r.json()
                if not isinstance(batch, list) or not batch:
                    break
                items.extend(batch)
                offset += 10
    except Exception as exc:  # 取得失敗は空リスト (呼び出し側は GIF 無しとして継続)
        logger.warning("exercisedb_equipment_fetch_failed", equipment=equipment, error=str(exc))
        return []

    try:
        cache.write_text(json.dumps(items))
    except OSError:
        pass
    return items


def list_candidates(name: str, *, limit: int = 6) -> list[dict[str, Any]]:
    """種目名の候補一覧 (器具限定 + キーワードスコア降順)。候補ピッカー UI 用。"""
    equipment = infer_equipment(name)
    pool = _fetch_equipment_pool(equipment)
    term = search_term(name) or _base(name)
    scored = sorted(pool, key=lambda e: _score(term, str(e.get("name", ""))), reverse=True)
    return [
        {
            "id": e.get("id"),
            "name": e.get("name"),
            "equipment": e.get("equipment"),
            "target": e.get("target"),
        }
        for e in scored[:limit]
        if e.get("id")
    ]


def auto_id(name: str) -> str | None:
    """curated 対象外の種目に対する自動候補の先頭 (該当なしなら None)。"""
    cands = list_candidates(name, limit=1)
    return cands[0]["id"] if cands else None


def resolve_id(name: str) -> str | None:
    """種目名 → GIF 取得に使う ExerciseDB ID。curated 優先、無ければ自動候補の先頭。"""
    return curated_id(name) or auto_id(name)


def fetch_detail_by_id(exercise_id: str) -> dict[str, Any] | None:
    """ExerciseDB の 1 件詳細 (id/name/equipment/target)。ディスクキャッシュ。"""
    cache = _cache_dir() / f"detail_{exercise_id}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except (OSError, ValueError):
            pass

    s = get_settings()
    if not s.exercisedb_api_key:
        return None
    headers = {"X-RapidAPI-Key": s.exercisedb_api_key, "X-RapidAPI-Host": s.exercisedb_host}
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.get(
                f"https://{s.exercisedb_host}/exercises/exercise/{exercise_id}", headers=headers,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("exercisedb_detail_fetch_failed", exercise_id=exercise_id, error=str(exc))
        return None
    if not isinstance(data, dict):
        return None
    detail = {
        "id": data.get("id"), "name": data.get("name"),
        "equipment": data.get("equipment"), "target": data.get("target"),
    }
    try:
        cache.write_text(json.dumps(detail))
    except OSError:
        pass
    return detail


def fetch_gif_by_id(exercise_id: str) -> bytes | None:
    """ExerciseDB の id 指定 GIF を取得。ディスクキャッシュ (id 単位、検索語のブレに影響されない)。"""
    cache = _cache_dir() / f"id_{exercise_id}.gif"
    if cache.exists():
        try:
            return cache.read_bytes()
        except OSError:
            pass

    s = get_settings()
    if not s.exercisedb_api_key:
        return None
    headers = {"X-RapidAPI-Key": s.exercisedb_api_key, "X-RapidAPI-Host": s.exercisedb_host}
    try:
        with httpx.Client(timeout=12.0) as client:
            # キーは RapidAPI ホストへの **ヘッダのみ** (URL に秘密を載せない)。
            g = client.get(
                f"https://{s.exercisedb_host}/image",
                headers=headers, params={"exerciseId": exercise_id, "resolution": "180"},
            )
            g.raise_for_status()
            if not g.headers.get("content-type", "").startswith("image"):
                return None
            gif = g.content
    except Exception as exc:  # 取得失敗は None (画面は GIF 無しで継続)
        logger.warning("exercisedb_image_fetch_failed", exercise_id=exercise_id, error=str(exc))
        return None

    try:
        cache.write_bytes(gif)
    except OSError:
        pass
    return gif


def get_gif(name: str) -> bytes | None:
    """種目名 (JA) → デモ GIF バイト列 (後方互換の一括ヘルパー)。マップ外/失敗は None。"""
    exercise_id = resolve_id(name)
    if exercise_id is None:
        return None
    return fetch_gif_by_id(exercise_id)


def exercise_key(name: str) -> str:
    """種目名の正規化キー (override テーブルの主キーに使う)。"""
    return _base(name)

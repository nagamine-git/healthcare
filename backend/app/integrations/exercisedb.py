"""ExerciseDB (RapidAPI) から種目デモ GIF を取得する。

方針: 我々の筋トレ種目は全てメジャー種目なので ExerciseDB に存在する。日本語名を英語の
検索語にマップし、GIF を取得してローカルにキャッシュ、バックエンドから配信する
(キーはサーバ側だけ・Tailscale 内完結・一度取れればオフラインでも出る)。
剣道素振り/シャドー/ジョグ/タバタ 等はマップに無い → GIF 無し (None)。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

# 括弧を除いた日本語種目名 (小文字・空白除去) → ExerciseDB 検索語 (英語)。
_JA_TO_EN: dict[str, str] = {
    "ダンベルベンチプレス": "dumbbell bench press",
    "ダンベルショルダープレス": "dumbbell shoulder press",
    "ダンベルルーマニアンデッドリフト": "dumbbell romanian deadlift",
    "ダンベルrdl": "dumbbell romanian deadlift",
    "ダンベルロー": "dumbbell row",
    "ダンベルゴブレットスクワット": "dumbbell goblet squat",
    "ゴブレットスクワット": "dumbbell goblet squat",
    "ダンベルランジ": "dumbbell lunge",
    "ダンベルスクワット": "dumbbell squat",
    "腕立て伏せ": "push up",
    "プッシュアップ": "push up",
    "パイクプッシュアップ": "pike push up",
    "インバーテッドロー": "inverted row",
    "スーパーマン": "superman",
    "自重スクワット": "bodyweight squat",
    "ブルガリアンスクワット": "bulgarian split squat",
    "ブルガリアン": "bulgarian split squat",
    "ピストルスクワット": "pistol squat",
    "ダンベルフライ": "dumbbell fly",
    "サイドレイズ": "dumbbell lateral raise",
    "ダンベルフレンチプレス": "dumbbell triceps extension",
    "ダンベルカール": "dumbbell curl",
    "ハンマーカール": "dumbbell hammer curl",
    "ダンベルリアレイズ": "dumbbell rear lateral raise",
    "ダンベルシュラッグ": "dumbbell shrug",
    "カーフレイズ": "dumbbell calf raise",
    "ダンベルステップアップ": "dumbbell step up",
    "ヒップスラスト": "hip thrust",
    "プランク": "plank",
    "レッグレイズ": "leg raise",
    "ダンベルサイドベンド": "dumbbell side bend",
    "デッドバグ": "dead bug",
    "ダンベルスラスター": "dumbbell thruster",
    "ダンベルスイング": "dumbbell swing",
    "ファーマーズマーチ": "farmers walk",
}


def _base(name: str) -> str:
    n = re.sub(r"[（(].*", "", name)
    return n.replace(" ", "").replace("　", "").strip().lower()


def search_term(name: str) -> str | None:
    """日本語種目名 → ExerciseDB 検索語。マップ外 (剣道/有酸素等) は None。"""
    base = _base(name)
    if base in _JA_TO_EN:
        return _JA_TO_EN[base]
    # 部分一致 (最長キー優先): "ダンベルロー (片手)" 等の付帯語を吸収
    for k in sorted(_JA_TO_EN, key=len, reverse=True):
        if k in base:
            return _JA_TO_EN[k]
    return None


def _cache_dir() -> Path:
    d = get_settings().app_data_dir / "exercise_gifs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_gif(name: str) -> bytes | None:
    """種目名 (JA) → デモ GIF バイト列。マップ外/キー未設定/失敗 は None。"""
    term = search_term(name)
    if term is None:
        return None
    slug = hashlib.sha1(term.encode()).hexdigest()[:16]
    cache = _cache_dir() / f"{slug}.gif"
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
            r = client.get(
                f"https://{s.exercisedb_host}/exercises/name/{term}",
                headers=headers, params={"limit": 1, "offset": 0},
            )
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                return None
            gif_url = data[0].get("gifUrl")
            if not gif_url:
                return None
            # gifUrl は ExerciseDB の公開 CDN。**キーは付けない** (URL に秘密を載せない/
            # 無関係ホストにヘッダで漏らさない)。認証必須の版なら取得失敗 → GIF 無しで継続。
            g = client.get(gif_url)
            g.raise_for_status()
            gif = g.content
    except Exception as exc:  # 取得失敗は None (画面は GIF 無しで継続)
        logger.warning("exercisedb_fetch_failed", name=name, term=term, error=str(exc))
        return None

    try:
        cache.write_bytes(gif)
    except OSError:
        pass
    return gif

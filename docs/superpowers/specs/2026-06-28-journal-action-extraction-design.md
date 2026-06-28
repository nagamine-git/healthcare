# 控えからの行動抽出(Journal Action Extraction)設計

## 目的
手書きジャーナルの控え(OCR テキスト)から「その日にやった良い行動」を推定し、
**確認ゲートを経て**庭(GoodActionLog)へバックフィルする。紙=入力、アプリ=読み出し+計算
という思想の延長。現状は控え保存で `journaling` 1件しか拾えていないのを一般化する。

## スコープ(確定した運用)
- **トリガー**: OCR 取込時に自動解析して提案。加えて保存済み控えに「行動を解析」ボタン。
- **確認デフォルト**: 高確信(`high`)のみ事前チェック ON、それ以外は OFF。**自動ログは禁止**。
- **抽出範囲**: シンプル抽出のみ(計画 vs 実績の差分は対象外。将来拡張)。
- 抽出は **garden_catalog の kind に限定**。マップできない自由記述は捨てる。
- **冪等**: `dedup_key = journal-extract:<date>:<kind>`。さらに commit 時、同日・同 kind の
  ログが既にあれば(手動チップ含む)スキップ=二重計上しない。
- ログの `source = "journal"`(手動/自動取込と区別、後から削除可能)。

## データフロー
```
控えテキスト ──LLM(journal_extract)──▶ [{kind, evidence, confidence}…]  (kind は catalog に限定)
                                          │  /api/journal/extract (記録しない)
                              提案リスト(根拠の一節 + 確信度 + already_logged)
                                          │  人が取捨選択・確認
                                          ▼  /api/journal/extract/commit {date, kinds}
                              GoodActionLog バックフィル(source=journal, 冪等)
                              → recompute_garden_for_date(date)
```

## API
- `POST /api/journal/extract` `{text, date?}` → `{proposals: [{kind, label, evidence, confidence, already_logged}]}`。**記録しない**。
- `POST /api/journal/extract/commit` `{date, kinds: [str]}` → 選択 kind をバックフィル(冪等)、庭再計算。`{logged: [str], today}`。

## バックエンド構成
- `app/llm/journal_extract.py`: `extract_actions(text, catalog) -> list[dict]|None`。保守的抽出、
  tool=`submit_actions`(配列 {kind, evidence, confidence})。api_key 無→None(UI はフォールバックで空提案)。
- `app/api/journal.py`: 上記2エンドポイント + `_log_extracted_action(session, date, kind) -> bool`
  (同日同 kind が既にあれば False、なければ source=journal で記録)。

## フロント(JournalArchive 内)
- OCR transcribe 成功 → draft セット → `extract(draft, today)` 自動実行 → 提案セクション表示。
- 保存済み控えの各行に「行動を解析」ボタン → その日付+テキストで extract → 同じ提案 UI。
- 提案 UI: kind ラベル + 根拠の一節 + 確信度バッジ。high は事前 ON、already_logged は ✓ 無効表示。
  「記録する」で commit → garden/today/life-tree/becoming を invalidate。

## リスクと対処
- **誤推定**: 必ず人が確認(高確信のみ事前 ON)。根拠の一節を必ず表示。保守的プロンプト。
- **二重計上**: dedup_key + 同日同 kind チェック。
- **OCR 精度**: 既存どおり「精度低い前提・要確認」を継承。抽出も確信度で段階表示。

## テスト
- extract: モック LLM で catalog 外 kind を除外することを検証。
- commit: 冪等(再 commit で増えない)、同日手動ログがあればスキップ。

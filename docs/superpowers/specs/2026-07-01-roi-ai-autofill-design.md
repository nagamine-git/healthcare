# ROI候補 AI自動補完 + Amazon wishlist取込 — 設計

## 目的
購入ROIランキングの候補追加で、品目名テキスト/商品画像/商品URL/過去データからAIが名前以外の全項目を根拠付きで推定しフォームに埋める(機能A)。さらにAmazon欲しいものリストURLから複数候補を一括吸い上げ(機能B)。手入力の摩擦を消す。

## 確定要件
- **入力ソース**: 品目名テキスト / 商品画像 / 商品URL / 過去データ(既存候補=相場観)、全部を総合的に
- **補完対象**: 名前以外の全項目 + 各項目に短い推定根拠(主観項目=削減時間/収益/活用日も叩き台+根拠)
- **wishlist取得**: URL自動取得を主経路、Amazon bot対策でのfetch失敗時はスクショOCRにフォールバック
- **確認フロー**: AI/wishlist結果は必ず画面で確認・編集してから保存(DBに自動保存しない)。既存の資産OCRと同方針。

## アーキテクチャ
共通基盤 `backend/app/llm/finance_roi_ai.py` (既存 `food.py`(テキスト→数値) + `finance_ocr.py`(画像) パターンの合流) が `RoiIn` 項目を推定。LLMは推定のみ、スコア計算は既存の決定的ロジック(`scoring/finance.py`)。

### 機能A: 単品補完 (Phase 1 = 基盤)
- `finance_roi_ai.py`:
  - `ROI_TOOL` = tool_use `submit_roi`。`fields`{cost_jpy, period(onetime|month|year), monthly_use_days, monthly_time_saved_h, monthly_revenue_jpy, resale_jpy, url, note} + `reasons`{各項目の1行根拠}
  - `_anthropic_suggest(*, name, url, image_b64, media_type, context, model, api_key)`: content=テキスト(名前/URL)+画像ブロック(任意)、context=既存候補の要約+時給(相場観)を system に注入
  - `_suggest = _anthropic_suggest` (テストで差し替え、ネットワーク非依存)
  - `suggest_roi(...)`: api_key無→None、失敗→None、fieldsを型/enum正規化して返す
- `POST /api/finance/roi-suggest` (`RoiSuggestIn`: name?, url?, image_base64?, media_type): 既存RoiCandidateをcontext化→suggest_roi→`{fields, reasons}`返す(保存しない)
- frontend `api.ts`: `financeRoiSuggest` + 型。`Finance.tsx` RoiSection: AI補完ボタン + 商品画像input + URL欄。結果を`setForm({...form,...fields})`でprefill、reasonsを各項目に表示。

### 機能B: wishlist一括 (Phase 2)
- `finance_roi_ai.py`: `extract_wishlist_items(html|image)` でLLM抽出(商品名/価格/URL)
- `POST /api/finance/roi-import-wishlist` (url? / images[]): url を httpx で UA偽装 fetch → LLM抽出 → 各itemを suggest_roi 補完 → 候補list返す。fetch失敗時は images(スクショ)フォールバック。保存しない。
- frontend: wishlist URL入力 → 抽出候補を一覧チェック → 選択分を一括追加(既存 financeRoi をループ)。

## テスト方針
- `food.py`同様 `_suggest`/`extract` を monkeypatch でモック(ネットワーク非依存)。`app_client` fixture 流用。
- `roi-suggest`: suggest_roi をモックし fields が返ることを検証。
- 正規化: period/status の enum 外・数値化・欠損を安全に補正。

## ついで直し(拡張時に一緒に)
- RoiSection 編集ボタン(`Finance.tsx:219-221`)の `monthly_use_days: 0` ハードコード → `RoiRow`+`compute_roi_ranking` に `monthly_use_days` を足して活用日消失バグを解消。
- フォームに `url`/`note` 欄を追加(スキーマに有るがUIに無い)。

## 段階デプロイ
Phase 1(基盤+単品)を実装→テスト→push(自動デプロイ)→確認。その後 Phase 2(wishlist)。BはAを使うため。

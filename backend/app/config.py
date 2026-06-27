from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_tz: str = "Asia/Tokyo"
    app_data_dir: Path = Path("/data")
    app_log_level: str = "INFO"

    db_path: Path | None = None

    anthropic_api_key: str | None = None
    # tool_use の安定性と料金のバランスで Sonnet 既定。Haiku だと focus/rationale が
    # 混線したり XML 疑似タグの混入が起きやすかったため格上げ。.env で上書き可。
    llm_model: str = "claude-sonnet-4-6"
    llm_max_regenerations_per_day: int = 3

    garmin_email: str | None = None
    garmin_password: str | None = None
    garmin_token_dir: Path | None = None

    hae_ingest_token: str | None = None

    baseline_window_days: int = 28
    morning_bb_hour_local: int = 6

    score_weight_sleep: float = 3.0
    score_weight_hrv: float = 2.0
    score_weight_bb: float = 2.0
    score_weight_load: float = 2.0
    score_weight_weight: float = 1.0
    score_weight_body_fat: float = 1.0

    score_version: str = "v2"

    # --- ユーザープロファイル (LLM プロンプトと採点で使用) ---
    # 以下は「例のプロファイル」。自分の値に合わせて環境変数 (USER_AGE, TARGET_WEIGHT_KG
    # 等) または .env で上書きする。採点と LLM 助言の個人化に使われる。
    user_age: int = 30
    user_sex: str = "male"  # "male" | "female"
    user_height_cm: float = 170.0
    # Karvonen 法の心拍ゾーン算出に使う安静時心拍。**覚醒・座位の安静時 HR** を入れること
    # (睡眠中の最低 HR ではない。睡眠中は 5-10 bpm 低く、これを使うと HRR が広がりゾーンが上振れする)。
    user_resting_hr: int = 60
    user_max_hr: int | None = None  # 実測最大心拍。None なら Tanaka 式 (208-0.7*age)
    user_chronotype: str = "intermediate"  # morning|intermediate|evening (睡眠/光曝露の助言)
    target_weight_kg: float = 65.0
    target_body_fat_pct: float = 18.0
    body_fat_tolerance_pct: float = 1.5

    # 利用可能な機材 (LLM 用)。ダンベル重量は **これ以外の刻みは存在しない**。
    user_equipment: list[str] = Field(
        default_factory=lambda: [
            "ダンベル (2 / 4 / 8 / 12 / 16 / 20 kg のいずれか。10kg や 6kg などの中間サイズは持っていない)",
            "アブローラー",
            "フラットベンチ",
            "プッシュアップバー (小型・2 つ)",
            "リュックサック (中身の重さで負荷調整可、加重足踏み・ラッキング用)",
            "トレーニングマット",
            "木刀 (素振り用)",
            "VR ヘッドセット (Meta Quest 系、VR boxing 等のフィットネスアプリ可)",
        ]
    )
    # 候補種目 (LLM はこの中から組む)
    user_training_options: list[str] = Field(
        default_factory=lambda: [
            # 有酸素 / コンディショニング (屋内・準備ゼロで始められる種目が基本。
            # 踏み台は無い。VR は装着が面倒なので基本提案しない。
            # ラッキングは「外に出られる場合の置き換え案」として notes に添えるのみ)
            "シャドーボクシング (素手 or 2kg ダンベル。準備ゼロ・静音、有酸素ベースの主役。"
            "3分動き続け+1分休憩のラウンド制、ジャブ/ストレート/フック + 前後ステップ)",
            "木刀素振り 連続 (休憩を詰めて心拍 130-140 を維持、有酸素 + 技術練習)",
            "ミリタリー自重サーキット (米軍 PRT / SEALs カリステニクス参考: "
            "プッシュアップ各種 (ワイド/ダイヤモンド/パイク) / スクワット / ランジ / "
            "マウンテンクライマー (スロー・低騒音) / プランク / デッドバグ。"
            "腰既往のためシットアップ・フラッターキック・ジャンプ系は使わない)",
            "自衛隊体操 (第一体操、約5分の全身体操。ウォームアップ / 回復日向き)",
            "加重足踏み (リュック加重のその場行進。回復日や ながら 運動向き)",
            "ダンベルコンプレックス (4-8kg×2 を床に置かず連続: ロー→ハングクリーン→"
            "ショルダープレス→スクワット等。心拍 135-150 の中強度サーキット。"
            "ヒンジ動作を含む場合は 12kg 上限)",
            "ファーマーズマーチ (12-16kg×2 を両手に提げてその場行進。握力・体幹・姿勢 + "
            "中強度有酸素。脊柱ニュートラル維持、すくめず肩を下げる)",
            "ラッキング (リュック歩行。屋外に出られる日のみ — 主提案にせず、"
            "屋内有酸素の notes に同負荷の置き換え案として添える)",
            "低騒音 HIIT (Tabata / EMOM、週 1-2 回上限。シャドーボクシング全力 / "
            "ダンベルスラスター等。ジャンプ系・バーピーは階下騒音のため避ける)",
            "室内ウォーキング/家事活動 (回復日の NEAT 確保)",
            # 木刀素振り (蹲踞姿勢、剣道系)
            "木刀素振り: 大素振り",
            "木刀素振り: 正面打ち",
            "木刀素振り: 面切り返し",
            "木刀素振り: 小手面胴切り返し",
            "木刀素振り: 股割り素振り (低姿勢、下半身強化)",
            # ダンベル筋トレ
            "ダンベルベンチプレス",
            "ダンベルショルダープレス",
            "ダンベルロー (片手)",
            "ダンベルゴブレットスクワット",
            "ダンベルルーマニアンデッドリフト (12kg 上限)",
            "ダンベルヒップスラスト",
            "ダンベルカール",
            "ダンベルランジ",
            # 自重
            "プッシュアップ (プッシュアップバー)",
            "アブローラー (膝つき)",
            "アブローラー (立位、上級)",
            "カーフレイズ (自重 / ダンベル加重)",
            "プランク",
            # モビリティ / 回復
            "動的ストレッチ (股関節 / 胸郭 / 肩)",
            "静的ストレッチ",
            "ボックスブレシング (呼吸法、副交感神経 ON)",
        ]
    )
    user_injury_notes: list[str] = Field(
        default_factory=lambda: [
            "16kg のダンベルデッドリフトで腰を痛めた経験あり。腰に高負荷をかけるヒンジ系は 12kg 以下、フォーム最優先。",
        ]
    )
    user_priority: str = (
        "仕事のパフォーマンス > 健康 > 魅力的な体型。"
        "睡眠とストレス管理を犠牲にしない範囲で目標体組成に近づけたい。"
        "提案の評価基準は次の優先順: ①科学的妥当性 (エビデンスの強さ) "
        "②医学的妥当性 (既往・安全性) ③ミリタリー的妥当性 (実戦的・機能的な体力: "
        "運搬力・持久力・全身協調) ④時間効率 ⑤コスト効率。"
        "下位基準のために上位基準を犠牲にしない (例: 時短でも根拠の弱い手法は採らない)。"
    )
    # 曜日固定はしない。直近 7-14 日の workout 履歴 + コンディションから
    # 「最も足りないモダリティ」を LLM が動的に選ぶ。週次目標分布だけ与える。
    # 科学的根拠: WHO 2020 (中強度有酸素 ≥ 150min/週 + 筋トレ 2 日/週)、
    # all-cause mortality は有酸素+筋トレ併用で -40% (Stamatakis 2018 BMJ)。
    # Z2 は時間より頻度の方が ROI 高い (ミトコンドリア生合成のメタ解析)。
    user_weekly_target_hint: str = (
        "週次目標分布 (曜日固定しない、直近履歴から動的に決める):\n"
        "- 筋トレ: 3 セッション/週 (push / pull / legs を回す。連日同部位は避け、48h 以上空ける)\n"
        "- Z2 有酸素: 3 セッション/週 (シャドーボクシング / 木刀素振り連続 / "
        "自重・ダンベルサーキット / 加重足踏み。屋内種目で確定提案。"
        "外に出られる日はラッキングへの置き換え可を notes に添える。"
        "頻度 > 時間。1 回 30-60 分で OK)\n"
        "- HIIT または ロング Z2: 1 セッション/週 (低騒音 Tabata 1 本 or 60-90 分の"
        "加重足踏み・シャドーボクシングロング)\n"
        "- 完全休 or 軽モビリティ: 1 セッション/週\n"
        "選択ロジック: ``recent_workouts_14d`` の直近 7 日を見て **最も不足しているモダリティ** "
        "を本日の候補にする。例: 直近 7 日が筋トレ 4・Z2 cardio 0 なら今日は Z2 を最優先。"
        "コンディションが悪ければ Z2 → ウォーキング、休息に格下げ。"
    )

    # --- 栄養目標 ---
    target_protein_g_per_kg: float = 2.0  # recomposition 想定
    target_water_ml_per_kg: float = 35.0
    # 摂取カロリー目標は TDEE (= 当日の active + basal energy 合計、Apple Health から推定) を基準にする

    # --- カフェイン薬物動態パラメータ ---
    # 1コンパートメント・1次吸収/1次消失 (Bateman) モデルで「就寝時血中濃度」を逆算する。
    # 個人差: CYP1A2 遺伝多型・喫煙 (誘導↑) ・経口避妊薬 (阻害↓) で T_half は 2-12h と幅がある。
    # 既定値は健常成人の平均 (Statland 1980, Carrillo 2000)。.env で個別調整可。
    caffeine_half_life_h: float = 5.0
    # 吸収半減期。カフェインは経口で速やかに吸収され ka≈4.9/h (吸収 T_half≈8.5min≈0.14h)、
    # tmax≈45min (Blanchard 1983, Newton 1981)。これで立ち上がり相を正しくモデル化する。
    caffeine_absorption_half_life_h: float = 0.14
    caffeine_vd_l_per_kg: float = 0.5
    # 就寝時の血中濃度がこれを下回れば睡眠への影響を最小化できる (Roehrs & Roth 2008)
    caffeine_bedtime_threshold_mg_per_l: float = 0.5
    # 認知効果が有意になる最低有効量 (Smith 2002 メタ解析、~1mg/kg)
    caffeine_min_cognitive_mg: float = 60.0
    # 目標摂取量 (mg/kg)。1.0 が標準、0.5-0.75 は感受性高い人 / 妊娠中
    caffeine_target_mg_per_kg: float = 1.0
    # カフェイン感受性 "high"|"normal"|"low" → 目標 mg/kg を派生 (UI 上書き可)
    caffeine_sensitivity: str = "normal"
    # 就寝何時間前以降は推奨しない (Drake 2013)
    caffeine_cutoff_hours_before_bed: float = 6.0
    # インスタントコーヒー 1g あたりカフェイン量 (AGF/Nescafe/UCC 平均 ≈ 60mg)
    instant_coffee_mg_per_g: float = 60.0

    # --- 鎮痛薬の用法 (臨床: バファリン/イブクイック とも添付文書ベース) ---
    # 服用間隔は 4 時間以上、1 日 3 回まで。早すぎる連用・過量を防ぐ。
    med_min_interval_h: float = 4.0
    med_max_doses_per_day: int = 3

    # --- 睡眠リズム目標 ---
    target_wake_time: str = "06:30"  # 平日想定の起床時刻 (HH:MM, JST)
    target_sleep_min: int = 480  # 8h を ideal とする (推奨 7-9h)
    bath_to_bed_lead_min: int = 90  # 入浴(上がる)〜就寝の理想ラグ (深部体温↑→↓ で入眠促進)
    bath_soak_duration_min: int = 12  # 湯船に浸かる時間 (入る=上がる−これ)。10-15分が目安
    bath_temp_c: int = 40  # 推奨湯温 (40-42℃)。受動的加温で寝つき改善 (Haghayegh 2019)
    dinner_to_bed_lead_min: int = 180  # 夕食〜就寝の理想ラグ (消化負荷を避ける)
    dinner_eat_duration_min: int = 40  # 夕食にかかる時間 (食べ始め=食べ終わり−これ)
    # 夕食の「遅すぎない上限」: 起床からこの時間以内に食べ終える (夜遅い食事は代謝/血糖に悪い
    # = 概日の摂食ミスアライメント; Morris 2015)。就寝逆算とこの絶対上限の早い方を採る。
    meal_last_h_after_wake: float = 13.0

    # --- トレーニング処方の開始重量 (前回実績が無いときの保守的スタート) ---
    # 腰のケガ歴を考慮し、ヒンジ系は 8kg から、全般に控えめに開始。
    # 利用可能な刻みは 2/4/8/12/16/20kg のみ なので、それ以外を絶対に使わない。
    # ダンベル系のみ "持っている刻み" の中の保守スタート値を列挙する。
    # 有酸素・ラッキング・木刀・VR boxing 等の時間・距離・reps は履歴 (recent_workouts_14d /
    # recent_training_prescriptions_21d) から LLM が動的算出するため、ここには持たない。
    user_starting_weights: dict[str, str] = Field(
        default_factory=lambda: {
            "ダンベルベンチプレス": "8kg×2",
            "ダンベルショルダープレス": "4kg×2",
            "ダンベルロー (片手)": "8kg",
            "ダンベルゴブレットスクワット": "8kg",
            "ダンベルルーマニアンデッドリフト": "8kg×2",
            "ダンベルヒップスラスト": "8kg×2",
            "ダンベルカール": "4kg×2",
            "ダンベルランジ": "4kg×2",
            "プッシュアップ (プッシュアップバー)": "自重",
            "アブローラー (膝つき)": "自重",
            "カーフレイズ": "自重 or 8kg×2",
        }
    )
    # 漸進性ルール: ダンベルが飛び石 (2→4→8→12→16→20) なので
    # 「次の刻み」へジャンプ。+2kg ではなく次の利用可能サイズへ。
    user_progression_rule: str = (
        "double progression: 同一重量で目標 reps 上限 + RIR 1-2 を 2 セッション連続で達成できたら "
        "**次に利用可能な重量** へ進む (例: 8kg → 12kg、12kg → 16kg)。達成できなければ重量維持して "
        "reps を 1 ずつ伸ばすか RIR を改善する。中間サイズ (10kg / 6kg 等) は存在しない。"
    )

    # --- 気圧 (片頭痛トリガー監視) ---
    # 例: 東京駅の座標。WEATHER_LATITUDE / WEATHER_LONGITUDE で自分の地域に上書きする。
    # 気圧降下 (前 24h で -6 hPa 以上) と片頭痛発症の相関が研究で示されている
    # (Mukamal 2009, Hoffmann 2015 等)。
    weather_latitude: float = 35.6812
    weather_longitude: float = 139.7671
    weather_location_label: str = "Tokyo"
    # 急降下とみなす閾値 (hPa)。前 24h での低下量 (絶対値) がこれを超えたら warning。
    pressure_drop_warning_hpa: float = 6.0
    # 重度の急降下閾値 (台風接近など)
    pressure_drop_severe_hpa: float = 10.0

    # --- ライフドメイン (自己目標管理) ---
    meditation_target_min: int = 15  # 1 日の瞑想目標分 (mindful_minutes 合計の目標)

    # --- Compass: 価値観 × マインドセット ---
    # 次元定義は scoring/identity/dimensions.py (枠組み定数)。ここに持つのは
    # 「理想プロファイル (どの次元をどこまで高めたいか)」= personal/aspirational target。
    # DB の IdentityArchetype が未設定のときの既定。env / UI で上書きできる。
    # 既定は「起業家 (founder) アーキタイプ」: マインドセット層と自律・達成・刺激を高く、
    # 同調・伝統・安全を低めに置く (脱・サラリーマンマインドの方向)。
    identity_archetype_name: str = "founder"
    identity_archetype_targets: dict[str, float] = Field(
        default_factory=lambda: {
            # 価値観層
            "self_direction": 90,
            "stimulation": 80,
            "hedonism": 45,
            "achievement": 85,
            "power": 65,
            "security": 35,
            "conformity": 25,
            "tradition": 25,
            "benevolence": 60,
            "universalism": 65,
            # マインドセット層
            "internal_locus": 90,
            "proactivity": 90,
            "effectuation": 85,
            "risk_tolerance": 80,
            "need_for_achievement": 88,
            "growth_mindset": 90,
            "ownership": 92,
        }
    )
    # 重み: 本人のギャップ (脱サラリーマンマインド) が大きいマインドセット層を重く。
    identity_archetype_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "self_direction": 2.0,
            "stimulation": 1.0,
            "hedonism": 0.5,
            "achievement": 1.5,
            "power": 0.8,
            "security": 0.8,
            "conformity": 1.0,
            "tradition": 0.8,
            "benevolence": 1.0,
            "universalism": 1.0,
            "internal_locus": 2.5,
            "proactivity": 2.5,
            "effectuation": 2.0,
            "risk_tolerance": 2.0,
            "need_for_achievement": 2.0,
            "growth_mindset": 2.0,
            "ownership": 2.5,
        }
    )
    # 現在地合成 EWMA の span (意思決定ログ観測数ベース)。
    identity_ewma_span: int = 8
    # 作品メタdata補完 API (任意)。未設定なら IMDb CSV の情報だけで動く。
    tmdb_api_key: str | None = None
    omdb_api_key: str | None = None

    # --- Garden(ゲーミフィケーション)---
    # personal: 行動カタログ(生活全般の「いい行動」。理想像への紐付けを含むので個人依存)。
    # source: 自動取得元 or "manual"。自動 = github / garmin_aerobic / garmin_strength /
    #         sleep / steps / learning。データ源が無い生活ドメインのみ manual。
    garden_catalog: list[dict] = Field(
        default_factory=lambda: [
            # --- 認知・創造(founder のアウトプット)---
            {"kind": "coding", "source": "github",
             "dimensions": ["self_direction", "proactivity", "ownership", "effectuation"],
             "base": 2.0, "evidence": "創造的アウトプット=founder 主体性の直接証拠"},
            {"kind": "creative", "source": "manual",
             "dimensions": ["self_direction", "ownership", "risk_tolerance"],
             "base": 1.8, "evidence": "作品/発信を世に出す=オーナーシップの実践"},
            {"kind": "deepwork", "source": "manual",
             "dimensions": ["need_for_achievement", "self_direction"],
             "base": 1.6, "evidence": "ディープワーク=高価値産出 (Newport 2016)"},
            {"kind": "reading", "source": "manual",
             "dimensions": ["growth_mindset", "effectuation", "universalism"],
             "base": 1.4, "evidence": "読書→知識・視点・言語ネットワーク"},
            {"kind": "learning", "source": "learning",
             "dimensions": ["growth_mindset", "self_direction"],
             "base": 1.4, "evidence": "意図的学習→成長マインドセット"},
            # --- 身体(脳と気力の土台)---
            {"kind": "aerobic", "source": "garmin_aerobic",
             "dimensions": ["risk_tolerance", "need_for_achievement", "growth_mindset"],
             "base": 1.5, "evidence": "有酸素運動→BDNF・実行機能 (Erickson 2011)"},
            {"kind": "strength", "source": "garmin_strength",
             "dimensions": ["need_for_achievement", "ownership"],
             "base": 1.5, "evidence": "筋トレ→自己効力感・実行機能・代謝"},
            {"kind": "sleep", "source": "sleep",
             "dimensions": ["internal_locus", "growth_mindset"],
             "base": 1.3, "evidence": "十分な睡眠→記憶定着・情動制御"},
            {"kind": "steps", "source": "steps",
             "dimensions": ["growth_mindset"],
             "base": 1.0, "evidence": "活動量→脳血流・気分"},
            {"kind": "nature", "source": "manual",
             "dimensions": ["growth_mindset"],
             "base": 1.0, "evidence": "自然・朝日→注意回復・概日リズム"},
            {"kind": "healthy_meal", "source": "manual",
             "dimensions": ["internal_locus"],
             "base": 1.0, "evidence": "自炊・整った食事→自己調整・血糖安定"},
            # --- メンタル・内省 ---
            {"kind": "meditation", "source": "manual",
             "dimensions": ["internal_locus", "growth_mindset"],
             "base": 1.2, "evidence": "瞑想→前頭前野・情動制御・HRV (Tang 2015)"},
            {"kind": "journaling", "source": "manual",
             "dimensions": ["growth_mindset", "internal_locus"],
             "base": 1.2, "evidence": "expressive writing (Pennebaker 1997)"},
            {"kind": "reflection", "source": "manual",
             "dimensions": ["growth_mindset", "ownership"],
             "base": 1.0, "evidence": "省察的実践 (Schön 1983)"},
            {"kind": "gratitude", "source": "manual",
             "dimensions": ["universalism", "growth_mindset"],
             "base": 0.9, "evidence": "感謝の記録→主観的幸福・向社会性"},
            # --- 人・生活(主体性/関係/基盤)---
            {"kind": "social", "source": "manual",
             "dimensions": ["proactivity", "benevolence"],
             "base": 1.3, "evidence": "人に会う/声をかける=社会資本・主体性"},
            {"kind": "family", "source": "manual",
             "dimensions": ["benevolence", "security"],
             "base": 1.1, "evidence": "家族との時間→関係資本・回復"},
            {"kind": "finance", "source": "manual",
             "dimensions": ["security", "ownership", "need_for_achievement"],
             "base": 1.1, "evidence": "家計・投資の前進→基盤づくり・主体性"},
        ]
    )
    # 自動判定のしきい値。
    garden_good_sleep_min: int = 420  # この分以上で「十分な睡眠」を 1 行動とみなす
    garden_steps_goal: int = 8000  # この歩数以上で「よく歩いた」を 1 行動とみなす

    # --- 健康診断(clinical: 成人の基準値。科学的に有効・行動につながる項目に限定)---
    # band [lo, hi]: 下回ると low / 上回ると high。片側は None。成人男性既定。
    checkup_items: list[dict] = Field(
        default_factory=lambda: [
            {"key": "bmi", "label": "BMI", "unit": "", "category": "体格", "lo": 18.5, "hi": 25.0},
            {"key": "sbp", "label": "収縮期血圧", "unit": "mmHg", "category": "血圧", "lo": 90, "hi": 129},
            {"key": "dbp", "label": "拡張期血圧", "unit": "mmHg", "category": "血圧", "lo": 60, "hi": 84},
            {"key": "ldl_c", "label": "LDLコレステロール", "unit": "mg/dL", "category": "脂質", "lo": None, "hi": 119},
            {"key": "hdl_c", "label": "HDLコレステロール", "unit": "mg/dL", "category": "脂質", "lo": 40, "hi": None},
            {"key": "tg", "label": "中性脂肪", "unit": "mg/dL", "category": "脂質", "lo": None, "hi": 149},
            {"key": "fasting_glucose", "label": "空腹時血糖", "unit": "mg/dL", "category": "血糖", "lo": 70, "hi": 99},
            {"key": "hba1c", "label": "HbA1c", "unit": "%", "category": "血糖", "lo": None, "hi": 5.5},
            {"key": "ast", "label": "AST(GOT)", "unit": "U/L", "category": "肝機能", "lo": None, "hi": 30},
            {"key": "alt", "label": "ALT(GPT)", "unit": "U/L", "category": "肝機能", "lo": None, "hi": 30},
            {"key": "ggt", "label": "γ-GTP", "unit": "U/L", "category": "肝機能", "lo": None, "hi": 50},
            {"key": "egfr", "label": "eGFR", "unit": "mL/min", "category": "腎機能", "lo": 60, "hi": None},
            {"key": "uric_acid", "label": "尿酸", "unit": "mg/dL", "category": "代謝", "lo": None, "hi": 7.0},
            {"key": "hemoglobin", "label": "ヘモグロビン", "unit": "g/dL", "category": "血液", "lo": 13.5, "hi": 17.5},
        ]
    )

    # --- Life Optimization OS(目的→目標→ドメイン木→行動)---
    life_freq_window_days: int = 14  # 行動頻度の集計窓
    life_freq_target_days: int = 7  # この日数で頻度達成度 100%
    # personal: 各 capital の維持フロア(これを割ると警告)。
    life_capital_floors: dict[str, float] = Field(
        default_factory=lambda: {
            "body": 55, "mind": 45, "intellect": 40,
            "creation": 40, "relationships": 40, "economy": 35,
        }
    )
    # personal: 既定の目標(seed)。capital_weights が重点ウェイトを駆動。
    life_default_goal: dict = Field(
        default_factory=lambda: {
            "title": "AI 活用でユニコーンを立ち上げる",
            "horizon": "2年",
            "capital_weights": {
                "creation": 2.5, "economy": 1.5, "intellect": 1.5,
                "mind": 1.2, "body": 1.0, "relationships": 1.0,
            },
        }
    )
    # tuning: ギャップ連動の効き具合。盲点(gap最大)は重み最大 (1+gamma) 倍。
    garden_gap_gamma: float = 1.0
    # intensity→level 0-4 の境界。
    garden_level_thresholds: list[float] = Field(
        default_factory=lambda: [0.0, 1.0, 2.5, 4.5]
    )
    # GitHub 認証フォールバック(通常は DB GardenConfig 優先)。
    github_username: str | None = None
    github_token: str | None = None

    # --- Becoming エンジン(三層フライホイール + 到達予測)---
    becoming_good_condition_threshold: float = 70.0  # personal: 「動ける」良好日の閾値
    becoming_trajectory_window_days: int = 90  # tuning: 傾き推定の窓
    becoming_min_snapshots_for_eta: int = 14  # tuning: これ未満は ETA 低信頼
    scheduler_becoming_snapshot_cron: str = "35 * * * *"

    scheduler_enabled: bool = True
    scheduler_garmin_cron: str = "5 * * * *"
    scheduler_recompute_cron: str = "15 * * * *"
    scheduler_morning_advice_cron: str = "30 6 * * *"
    scheduler_baseline_cron: str = "0 3 * * *"
    # 通知 tick: 毎分「今送るべき通知」を判定して Web Push を送る。
    # アクションの time_jst は分単位なので、ピッタリその分に発火させるため毎分回す
    # (NotificationLog による冪等判定があるので毎分でも二重送信しない)。
    scheduler_notify_cron: str = "* * * * *"
    # Compass: 週次で意思決定ログを集計して現在地を更新 (月曜 8:00 JST)。
    scheduler_identity_weekly_cron: str = "0 8 * * 1"
    # Compass: 月初に SJT 本測リマインドを出す (1 日 8:00 JST)。
    scheduler_identity_monthly_cron: str = "0 8 1 * *"
    # Garden: GitHub コミット取込(毎時20分)→ 草の再計算(毎時25分)。
    scheduler_github_sync_cron: str = "20 * * * *"
    scheduler_garden_recompute_cron: str = "25 * * * *"

    # --- Web Push 通知 ---
    # VAPID 鍵ペア。private は秘密 (1Password 等)、public はブラウザにも渡る applicationServerKey。
    # base64url 文字列で渡す (bin/gen-vapid-keys.py で生成)。未設定なら通知は無効。
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    # VAPID の連絡先 (mailto: か https URL)。push サービスが配信不能時に連絡するための識別子。
    vapid_subject: str = "mailto:admin@example.com"
    # 通知サブシステム全体の ON/OFF。
    push_enabled: bool = True
    # 就寝リマインドを送るか。
    push_bedtime_reminder: bool = True
    # critical アラート digest を出し始める時刻 (時)。早朝の就寝中に鳴らさないため。
    push_critical_after_hour: int = 7

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path
        return self.app_data_dir / "healthcare.sqlite3"

    def resolved_garmin_token_dir(self) -> Path:
        if self.garmin_token_dir is not None:
            return self.garmin_token_dir
        return self.app_data_dir / "garmin_tokens"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()

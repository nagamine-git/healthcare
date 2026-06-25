"""天気予報・降水確率 (Open-Meteo best_match)。

# データソース
Open-Meteo `forecast` API を models 未指定 (best_match = 地点ごとの最適モデル自動選択) で叩く。
key 不要・無料・商用可。気象庁モデル (jma_seamless) は降水確率を提供しない (全 None) ため、
降水確率を出す本機能では best_match を使う (日本では高解像度モデルの合議で確率込みの予報)。

- hourly: 気温・降水量・降水確率・天気コード・湿度・風 (今日明日の時間別に使う)
- daily: 天気コード・最高/最低気温・降水確率最大・日の出入り (7日週間に使う)

1 時間キャッシュ。気圧・大気質 (weather.py) とは責務を分けてこのモジュールに置く。
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_CACHE_TTL_S = 60 * 60  # 1h
_cache: dict[str, tuple[float, Any]] = {}

_JST = ZoneInfo("Asia/Tokyo")

# WMO weathercode → (日本語ラベル, アイコンキー)。アイコンキーはフロントの lucide にマップ。
_CODE_MAP: dict[int, tuple[str, str]] = {
    0: ("快晴", "sun"),
    1: ("晴れ", "sun"),
    2: ("薄曇り", "cloud-sun"),
    3: ("曇り", "cloud"),
    45: ("霧", "fog"),
    48: ("霧(着氷)", "fog"),
    51: ("弱い霧雨", "drizzle"),
    53: ("霧雨", "drizzle"),
    55: ("強い霧雨", "drizzle"),
    56: ("着氷性の霧雨", "drizzle"),
    57: ("着氷性の霧雨", "drizzle"),
    61: ("弱い雨", "rain"),
    63: ("雨", "rain"),
    65: ("強い雨", "rain"),
    66: ("着氷性の雨", "rain"),
    67: ("着氷性の雨", "rain"),
    71: ("弱い雪", "snow"),
    73: ("雪", "snow"),
    75: ("強い雪", "snow"),
    77: ("霧雪", "snow"),
    80: ("にわか雨", "rain"),
    81: ("にわか雨", "rain"),
    82: ("激しいにわか雨", "rain"),
    85: ("にわか雪", "snow"),
    86: ("にわか雪", "snow"),
    95: ("雷雨", "storm"),
    96: ("雷雨(雹)", "storm"),
    99: ("雷雨(雹)", "storm"),
}


def weather_code_to_label(code: int | None) -> tuple[str, str]:
    """WMO weathercode を日本語ラベルとアイコンキーに変換する。不明は ('不明','unknown')。"""
    if code is None:
        return ("不明", "unknown")
    return _CODE_MAP.get(int(code), ("不明", "unknown"))


_DAY_START = 6  # 干す現実的な時間帯 (時)
_DAY_END = 18
# 濡れ被害の飽和: 降水量 _WET_SAT_LO mm 未満は実害ほぼ無し (蒸発/庇)、_WET_SAT_HI mm 以上は
# 「確実に濡れる」で飽和 (0.5mm でも 20mm でも干した服が濡れる結果は同じ)。線形ではなく
# この飽和カーブで「降る場合の被害」を表す。
_WET_SAT_LO = 0.1
_WET_SAT_HI = 1.0
# 濡れリスク = (降水確率/100) × (0.5 + 0.5×濡れ被害)。確率が主、量で被害を上乗せする。
# しきい値で 3 段階に離散化する。
_DRY_RISK = 0.18  # これ未満なら気兼ねなく干せる (例: 確率35%・雨量0 ≒ 0.175)
_NO_RISK = 0.40  # これ以上は外干し不可 (例: 確率80%・本降り、確率90%・微量 等)


def _wet_severity(precip: float | None) -> float:
    """降水量 (mm) → 濡れ被害 0-1 (飽和)。_WET_SAT_LO 未満=0、_WET_SAT_HI 以上=1。"""
    p = precip or 0.0
    if p < _WET_SAT_LO:
        return 0.0
    if p >= _WET_SAT_HI:
        return 1.0
    return (p - _WET_SAT_LO) / (_WET_SAT_HI - _WET_SAT_LO)


def _slot_risk(s: dict[str, Any]) -> float | None:
    """1 スロットの濡れリスク (0-1)。確率が無ければ None (判定不能)。"""
    p = s.get("prob")
    if p is None:
        return None
    return (float(p) / 100.0) * (0.5 + 0.5 * _wet_severity(s.get("precip")))


def _slot_tier(s: dict[str, Any]) -> str:
    """スロットを dry (干せる) / caution (干せるが注意) / no (不可) / unknown に段階化。"""
    risk = _slot_risk(s)
    if risk is None:
        return "unknown"
    if risk >= _NO_RISK:
        return "no"
    if risk >= _DRY_RISK:
        return "caution"
    return "dry"


# --- 乾燥力 (蒸発ポテンシャル) ---
# 洗濯物が乾くのは蒸発で、主因は日射 (短波放射) > 湿度 > 気温。雨が降らなくても
# 夕方や曇天では日射が弱く「干しても乾かない」。狙い目から実用的に外すための指標。
_RAD_MIN = 80.0  # W/m^2: これ未満は日射による乾燥がほぼ期待できない (朝夕・曇天)
_RAD_GOOD = 350.0  # これ以上で日射の乾燥力はほぼ満点 (晴れた日中の目安)
_HUM_DRY = 45.0  # この湿度(%)以下で乾きやすい
_HUM_WET = 90.0  # この湿度以上はほぼ乾かない
_DRY_POWER_MIN = 0.25  # 乾燥力がこれ未満なら「干しても乾きにくい」= 狙い目に含めない

# 乾燥時間の推定: 乾燥力 (0-1) を「率」とみなし、累積 power-hours が _DRY_DOSE に達したら乾いた
# とみなす。晴天 (power~0.85) で約 3.5h、中程度 (0.5) で約 6h、曇天 (0.3) で約 10h の感覚に合わせる。
_DRY_DOSE = 3.0
# 生乾き臭/カビの目安。洗濯物が ~5 時間で乾かないと雑菌 (モラクセラ菌) が増え生乾き臭の温床。
_DRY_MOLD_MINUTES = 300
# 乾燥力不足 (夜・本格的な曇天) がこれだけ連続したら、その回の乾燥は不成立とする (夜またぎ防止)。
_DRY_STALL_BREAK_MIN = 120
_DRY_STEP_MIN = 5  # 分単位推定の刻み

# --- 風 (m/s) ---
# 弱〜中の風は飽和空気を入れ替えて乾燥を速める。中風で頭打ち (それ以上は飛散リスクが勝る)。
_WIND_DRY_FULL = 5.0  # この風速で乾燥ブーストが最大
_WIND_DRY_BONUS = 0.25  # 最大 +25%
# 突風 (gust) による飛散ハザード。Beaufort 5 相当で飛びやすく、6 相当で外干し不可。
_WIND_GUST_CAUTION = 8.0  # これ以上は「飛びやすい・しっかり留める」
_WIND_GUST_HAZARD = 11.0  # これ以上は「飛ぶ恐れ・外干し不可」

_DIR16 = [
    "北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
    "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西",
]


def _dir_label(deg: float | None) -> str | None:
    """風向 (度, 気象=吹いてくる方角) を16方位の日本語に変換。"""
    if deg is None:
        return None
    return _DIR16[int((float(deg) % 360) / 22.5 + 0.5) % 16]


def _gust_level(s: dict[str, Any]) -> str:
    """突風による飛散リスク: ok / caution (飛びやすい) / hazard (飛ぶ恐れ)。"""
    g = s.get("gust")
    if g is None:
        return "ok"
    g = float(g)
    if g >= _WIND_GUST_HAZARD:
        return "hazard"
    if g >= _WIND_GUST_CAUTION:
        return "caution"
    return "ok"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _drying_power(s: dict[str, Any]) -> float | None:
    """日射・湿度・風から乾燥力 (0-1) を返す。日射データが無ければ None (判定不能)。

    None のときは呼び出し側で「雨だけで判定」にフォールバックする (データ欠損で
    既存挙動を壊さないため)。
    """
    rad = s.get("radiation")
    if rad is None:
        return None
    rad_f = _clamp01((float(rad) - _RAD_MIN) / (_RAD_GOOD - _RAD_MIN))
    hum = s.get("humidity")
    hum_f = 1.0 if hum is None else _clamp01((_HUM_WET - float(hum)) / (_HUM_WET - _HUM_DRY))
    # 日射が主、湿度で減衰 (高湿度だと乾きにくい)。
    base = rad_f * (0.4 + 0.6 * hum_f)
    # 弱〜中の風は蒸発を助ける (m/s)。_WIND_DRY_FULL で頭打ち。
    wind = s.get("wind")
    if wind is not None:
        base *= 1.0 + min(float(wind), _WIND_DRY_FULL) / _WIND_DRY_FULL * _WIND_DRY_BONUS
    return min(1.0, base)


def _hangable_tier(s: dict[str, Any]) -> str | None:
    """雨・乾燥力・突風すべてを満たす「干せる」スロットの tier。不適なら None。"""
    if _gust_level(s) == "hazard":
        return None  # 強風で飛ぶ恐れ
    tier = _slot_tier(s)
    if tier not in ("dry", "caution"):
        return None  # 雨リスクで不可
    dp = _drying_power(s)
    if dp is not None and dp < _DRY_POWER_MIN:
        return None  # 日射不足/高湿で乾かない (夕方・曇天)
    # 突風が強め (飛びやすい) なら caution 扱いに落とす。
    if _gust_level(s) == "caution" and tier == "dry":
        return "caution"
    return tier


def laundry_advice(slots: list[dict[str, Any]], now_hour: int) -> dict[str, Any]:
    """今日の時間別から「今干せるか」「いつ干すべきか (時間帯)」を返す。

    slots: [{"hour", "prob", "precip", "temp", "humidity", "radiation"}]
    濡れリスク = 降水確率 × 飽和させた降水量。さらに日射 (短波放射) と湿度から乾燥力を見て、
    「雨が降らない かつ ちゃんと乾く」時間帯だけを狙い目にする (夕方・曇天は日射不足で除外)。
    最長の連続区間を採用 (同点なら雨量の少ない方)。
    """
    future = sorted(
        (s for s in slots if _DAY_START <= s["hour"] <= _DAY_END and s["hour"] >= now_hour),
        key=lambda s: s["hour"],
    )

    # 「雨が降らず・乾く」時間が連続する区間を集める。長さ・最大雨量・最大確率も持つ。
    runs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for s in future:
        tier = _hangable_tier(s)
        if tier is not None:
            precip = s.get("precip") or 0.0
            prob = s.get("prob") or 0
            if cur is None:
                cur = {
                    "start": s["hour"], "end": s["hour"],
                    "max_precip": precip, "max_prob": prob, "worst": tier,
                }
            else:
                cur["end"] = s["hour"]
                cur["max_precip"] = max(cur["max_precip"], precip)
                cur["max_prob"] = max(cur["max_prob"], prob)
                if tier == "caution":
                    cur["worst"] = "caution"
        else:
            if cur is not None:
                runs.append(cur)
            cur = None
    if cur is not None:
        runs.append(cur)

    # 最長を採用。同点は「雨量が少ない→確率が低い」を優先 (より安全な区間)。
    best = (
        max(runs, key=lambda r: (r["end"] - r["start"], -r["max_precip"], -r["max_prob"]))
        if runs
        else None
    )

    window: dict[str, str] | None = None
    hours = 0
    worst = "dry"
    if best is not None:
        window = {"start": f"{best['start']:02d}:00", "end": f"{best['end'] + 1:02d}:00"}
        hours = best["end"] - best["start"] + 1
        worst = best["worst"]

    in_day = _DAY_START <= now_hour <= _DAY_END
    now_slot = next((s for s in slots if s["hour"] == now_hour), None)
    has_now = in_day and now_slot is not None
    now_rain = _slot_tier(now_slot) if has_now else "unknown"
    now_dp = _drying_power(now_slot) if has_now else None
    now_gust = _gust_level(now_slot) if has_now else "ok"
    low_sun_now = now_dp is not None and now_dp < _DRY_POWER_MIN
    # 「今すぐ干せる」= 雨の心配が無く (dry)・乾く (日射十分)・突風ハザードが無い。
    can_now = now_rain == "dry" and not low_sun_now and now_gust != "hazard"

    if hours >= 3 and worst == "dry":
        level = "ok"
    elif hours >= 1:
        level = "caution"
    elif not in_day:
        level = "unknown"  # 夜など日中外
    else:
        level = "no"

    if not in_day:
        now_text = "今は夜。外干しは日中に"
    elif now_gust == "hazard":
        now_text = "今は強風で外干し不可(飛ぶ恐れ)"
    elif now_rain in ("no", "unknown"):
        now_text = "今は外干しに不向き"
    elif low_sun_now:
        now_text = "今は干せるが乾きにくい(日射不足)"
    elif now_gust == "caution":
        now_text = "今は干せるが強風注意(しっかり留める)"
    elif now_rain == "caution":
        now_text = "今は干せるが注意"
    else:
        now_text = "今は干してOK"

    if window is None:
        window_text = "今日の日中は外干し非推奨"
    elif worst == "caution":
        window_text = f"狙い目 {window['start']}〜{window['end']}(にわか雨に注意)"
    else:
        window_text = f"狙い目 {window['start']}〜{window['end']}"

    return {
        "level": level,
        "can_now": can_now,
        "now_text": now_text,
        "window": window,
        "window_text": window_text,
    }


_WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def _time_label(t: datetime, today: date) -> str:
    """分単位の時刻ラベル。今日は時刻のみ、明日は「明日 HH:MM」、それ以降は曜日付き。"""
    d = t.date()
    if d == today:
        prefix = ""
    elif d == today + timedelta(days=1):
        prefix = "明日 "
    else:
        prefix = f"{_WEEKDAY_JA[t.weekday()]}曜 "
    return f"{prefix}{t.strftime('%H:%M')}"


def _lerp(va: Any, vb: Any, f: float) -> float | None:
    if va is None or vb is None:
        return va if vb is None else vb
    return float(va) + (float(vb) - float(va)) * f


def _interp_at(slots: list[dict[str, Any]], t: datetime) -> dict[str, Any] | None:
    """時刻 t における各値を、前後の毎時スロットから線形補間する。範囲外は None。"""
    if not slots or t < slots[0]["dt"] or t > slots[-1]["dt"]:
        return None
    for i in range(len(slots) - 1):
        a, b = slots[i], slots[i + 1]
        if a["dt"] <= t <= b["dt"]:
            span = (b["dt"] - a["dt"]).total_seconds() or 1.0
            f = (t - a["dt"]).total_seconds() / span
            keys = ("prob", "precip", "humidity", "radiation", "wind", "gust")
            return {k: _lerp(a.get(k), b.get(k), f) for k in keys}
    return None


def next_drying_window(slots: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """今から先で「次に干せるベストな時刻」を分単位で推定する。

    slots: 毎時 (dt 昇順) の {dt, prob, precip, humidity, radiation, wind}。
    乾燥力を率とみなして積分し、累積が _DRY_DOSE に達した時刻を「乾く時刻」とする。
    最初に成立する開始時刻 (= 早く干すほど早く乾く) を返す。雨で中断/夜で長時間停滞
    したら不成立として次を探す。見つからなければ None。

    返り値: {start, start_label, dry_by, dry_by_label, minutes, within_5h, blocked_by}
    """
    if len(slots) < 2:
        return None
    today = now.date()
    horizon = slots[-1]["dt"]
    step = timedelta(minutes=_DRY_STEP_MIN)

    def blocked(env: dict[str, Any] | None) -> bool:
        # 雨で濡れる、または強風で飛ぶ → 干せない。
        return env is not None and (_slot_tier(env) == "no" or _gust_level(env) == "hazard")

    def power(env: dict[str, Any] | None) -> float:
        if env is None:
            return 0.0
        dp = _drying_power(env)
        return dp if dp is not None else 0.0

    # now を刻みに丸めて開始候補をスキャン。
    minute = (now.minute // _DRY_STEP_MIN + 1) * _DRY_STEP_MIN
    t = now.replace(second=0, microsecond=0, minute=0) + timedelta(minutes=minute)
    while t < horizon:
        env = _interp_at(slots, t)
        ok_start = env is not None and not blocked(env) and power(env) >= _DRY_POWER_MIN
        if not ok_start:
            t += step
            continue
        # ここから乾燥を積分。
        dose, u, stalled, failed, wind_caution = 0.0, t, 0, False, False
        while dose < _DRY_DOSE and u < horizon:
            e = _interp_at(slots, u)
            if blocked(e):
                failed = True  # 雨で濡れる or 強風で飛ぶ → この回は不成立
                break
            if e is not None and _gust_level(e) == "caution":
                wind_caution = True
            p = power(e)
            if p < _DRY_POWER_MIN:
                stalled += _DRY_STEP_MIN
                if stalled >= _DRY_STALL_BREAK_MIN:
                    failed = True  # 日没など長時間停滞 → その回は乾き切らない
                    break
            else:
                stalled = 0
            dose += p * (_DRY_STEP_MIN / 60.0)
            u += step
        if not failed and dose >= _DRY_DOSE:
            minutes = int((u - t).total_seconds() // 60)
            return {
                "start": t.strftime("%H:%M"),
                "start_label": _time_label(t, today),
                "dry_by": u.strftime("%H:%M"),
                "dry_by_label": _time_label(u, today),
                "minutes": minutes,
                "within_5h": minutes <= _DRY_MOLD_MINUTES,
                "wind_caution": wind_caution,
                "blocked_by": None,
            }
        # 不成立 → 失敗地点の先へジャンプして次の開始候補を探す。
        t = u + step
    return None


def _safe_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _shape_forecast(raw: dict[str, Any], now_jst: datetime) -> dict[str, Any]:
    """Open-Meteo 生 JSON を {summary, hourly[], daily[]} に整形する。"""
    h = raw.get("hourly") or {}
    times = h.get("time", [])
    temps = h.get("temperature_2m", [])
    precs = h.get("precipitation", [])
    probs = h.get("precipitation_probability", [])
    codes = h.get("weathercode", [])
    hums = h.get("relative_humidity_2m", [])
    winds = h.get("wind_speed_10m", [])
    rads = h.get("shortwave_radiation", [])
    uvs = h.get("uv_index", [])
    gusts = h.get("wind_gusts_10m", [])
    wdirs = h.get("wind_direction_10m", [])

    def _g(arr: list, i: int) -> Any:
        return arr[i] if i < len(arr) else None

    hourly: list[dict[str, Any]] = []
    for i, t in enumerate(times):
        dt = _safe_dt(t)
        if dt is None or dt < now_jst:  # 過去の時間は出さない
            continue
        if len(hourly) >= 48:  # 今日明日 (最大48h) まで
            break
        code = _g(codes, i)
        label, icon = weather_code_to_label(code)
        hourly.append({
            "time": t,
            "temp": _g(temps, i),
            "precip": _g(precs, i),
            "precip_prob": _g(probs, i),
            "code": code,
            "label": label,
            "icon": icon,
            "humidity": _g(hums, i),
            "wind": _g(winds, i),
            "gust": _g(gusts, i),
            "wind_dir": _dir_label(_g(wdirs, i)),
            "radiation": _g(rads, i),
            "uv": _g(uvs, i),
        })

    d = raw.get("daily") or {}
    dtimes = d.get("time", [])
    dcodes = d.get("weathercode", [])
    dmax = d.get("temperature_2m_max", [])
    dmin = d.get("temperature_2m_min", [])
    dprob = d.get("precipitation_probability_max", [])
    duv = d.get("uv_index_max", [])
    daily: list[dict[str, Any]] = []
    for i, dte in enumerate(dtimes):
        code = _g(dcodes, i)
        label, icon = weather_code_to_label(code)
        daily.append({
            "date": dte,
            "code": code,
            "label": label,
            "icon": icon,
            "t_max": _g(dmax, i),
            "t_min": _g(dmin, i),
            "precip_prob_max": _g(dprob, i),
            "uv_max": _g(duv, i),
        })

    # 今日の時間別から「今干せるか・いつ干すべきか」を算出する。
    today = now_jst.date()
    today_slots: list[dict[str, Any]] = []
    future_slots: list[dict[str, Any]] = []  # 次の狙い目推定用 (今日明日の未来を毎時)
    for i, t in enumerate(times):
        dt = _safe_dt(t)
        if dt is None:
            continue
        if dt.date() == today:
            today_slots.append({
                "hour": dt.hour,
                "prob": _g(probs, i),
                "precip": _g(precs, i),
                "temp": _g(temps, i),
                "humidity": _g(hums, i),
                "radiation": _g(rads, i),
                "wind": _g(winds, i),
                "gust": _g(gusts, i),
            })
        if dt >= now_jst:
            future_slots.append({
                "dt": dt,
                "prob": _g(probs, i),
                "precip": _g(precs, i),
                "humidity": _g(hums, i),
                "radiation": _g(rads, i),
                "wind": _g(winds, i),
                "gust": _g(gusts, i),
            })
    laundry = laundry_advice(today_slots, now_jst.hour)
    # 次に干せるベストな時刻 (分単位) と乾く時刻・5h 判定。
    laundry["next"] = next_drying_window(future_slots, now_jst)

    # 直近の風 (向き・速度・突風)。情報表示用 (方角は乾燥判定には使わない)。
    wind_now: dict[str, Any] | None = None
    if hourly:
        h0 = hourly[0]
        wind_now = {
            "speed": h0.get("wind"),
            "gust": h0.get("gust"),
            "dir": h0.get("wind_dir"),
            "level": _gust_level({"gust": h0.get("gust")}),
        }

    summary: dict[str, Any] | None = None
    if daily:
        d0 = daily[0]
        summary = {
            "code": d0["code"],
            "label": d0["label"],
            "icon": d0["icon"],
            "t_max": d0["t_max"],
            "t_min": d0["t_min"],
            "precip_prob_max": d0["precip_prob_max"],
            "uv_max": d0.get("uv_max"),
            "wind": wind_now,
            "laundry": laundry,
        }

    return {"summary": summary, "hourly": hourly, "daily": daily}


def _fetch(lat: float, lon: float) -> dict[str, Any] | None:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": (
            "temperature_2m,precipitation,precipitation_probability,"
            "weathercode,relative_humidity_2m,wind_speed_10m,"
            "wind_gusts_10m,wind_direction_10m,shortwave_radiation,uv_index"
        ),
        "daily": (
            "weathercode,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,uv_index_max,sunrise,sunset"
        ),
        "timezone": "Asia/Tokyo",
        "wind_speed_unit": "ms",  # 風は m/s で扱う (洗濯判定のしきい値が m/s 基準)
        "forecast_days": 7,
    }
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("weather_forecast_fetch_failed", error=str(exc))
        return None


def _now_jst() -> datetime:
    return datetime.now(_JST).replace(tzinfo=None)


def get_weather_forecast(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    now_jst: datetime | None = None,
) -> dict[str, Any] | None:
    """整形済みの天気予報 {summary, hourly[], daily[]} を返す。失敗時は None。"""
    s = get_settings()
    lat = latitude if latitude is not None else s.weather_latitude
    lon = longitude if longitude is not None else s.weather_longitude
    key = f"{lat:.4f}_{lon:.4f}"

    mono = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and mono - cached[0] < _CACHE_TTL_S:
        raw = cached[1]
    else:
        raw = _fetch(lat, lon)
        if raw is not None:
            _cache[key] = (mono, raw)
    if raw is None:
        return None
    return _shape_forecast(raw, now_jst or _now_jst())

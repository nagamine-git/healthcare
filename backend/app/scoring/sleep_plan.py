"""今夜のスリープリズムを起床時刻から逆算する。

- 起床時刻 (config の target_wake_time) を翌日として固定
- bedtime = wake - target_sleep_min
- bath_time = bedtime - bath_to_bed_lead_min
- dinner_cutoff = bedtime - dinner_to_bed_lead_min

夜遅くにトレーニングがあるなど現実的に難しい場合は LLM 側で調整するため、
ここでは「理想の時刻」を返すだけにとどめる。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings

# 概日リズムの前進は行動・光で1日~30-60分が限界 (Burgess/Eastman)。
# 一気に理想へ飛ばさず、習慣の就寝から最大この分だけ前倒しする。
MAX_ADVANCE_MIN = 45


def _parse_hhmm(s: str) -> time:
    h, _, m = s.partition(":")
    return time(int(h), int(m))


def _habitual_phase(target: date_type, *, days: int = 14) -> dict[str, float] | None:
    """直近の実睡眠から習慣的な就寝時刻(h)・睡眠時間(min)を median 推定。"""
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MetricSample, SleepSession

    lo = datetime.combine(target - timedelta(days=days), datetime.min.time())
    with session_scope() as ses:
        durs = sorted(
            float(t) for (t,) in ses.execute(
                select(SleepSession.total_min).where(SleepSession.date >= target - timedelta(days=days))
            ).all() if t
        )
        mids = sorted(
            float(v) for (v,) in ses.execute(
                select(MetricSample.value).where(
                    MetricSample.metric_key == "sleep_midpoint_hour", MetricSample.ts >= lo
                )
            ).all() if v is not None
        )
    if not durs or not mids:
        return None
    dur = durs[len(durs) // 2]
    mid = mids[len(mids) // 2]  # JST hour (早朝は 0-9)
    return {"midpoint_h": mid, "dur_min": dur, "bedtime_h": mid - dur / 120.0}


def compute_tonight_plan(
    target: date_type,
    *,
    last_training_end_jst: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """target の「今夜→翌朝」のリズムを返す。

    Args:
        target: 今日の日付 (JST)
        last_training_end_jst: 当日のトレーニング終了時刻 (JST aware datetime)。
            これより後の bath / bedtime しか取れない場合は調整する。
        now: 現在時刻 (JST aware)。省略時は実時刻。日付が変わった直後〜起床前
            (深夜0時台など) に呼ばれた場合、「昨夜からの続き」として扱い、
            起床は target 自身の朝 (target+1 の翌朝ではなく) を指す。

    Returns:
        ``{wake, bedtime, bath, dinner_cutoff}`` 各 HH:MM 文字列、
        + メタ情報 (compressed: 理想に届かない bool, sleep_min_estimate, notes,
        sleep_now: 目安の就寝時刻をすでに過ぎている bool)
    """
    s = get_settings()
    tz = ZoneInfo(s.app_tz)
    now_dt = now if now is not None else datetime.now(tz)

    # 起床時刻・必要睡眠量は個人設定 (resolve_profile) を優先
    from app.scoring.profile import resolve_profile
    prof = resolve_profile()
    target_sleep_min = prof.sleep_need_min

    wake_t = _parse_hhmm(prof.wake_time)
    # 通常は wake = target + 1 day (今日の夜→明朝)。ただし日付境界が 00:00 な一方
    # 起床は朝なので、深夜0時台〜起床前に呼ばれた時は「まだ target 自身の朝を迎えて
    # いない」= 前夜からの継続中。その場合は target 自身の朝を wake にする。
    today_wake_dt = datetime.combine(target, wake_t, tz)
    in_progress_night = now_dt < today_wake_dt
    wake_dt = today_wake_dt if in_progress_night else today_wake_dt + timedelta(days=1)
    ideal_bedtime_dt = wake_dt - timedelta(minutes=target_sleep_min)

    notes: list[str] = []
    # 実睡眠データから「習慣的な就寝」を取り、理想へ一気に飛ばさず realistic に前倒し。
    # (固定の理想時刻だけ出すと実態と矛盾し、睡眠ドライバー分析とも食い違う)
    bedtime_dt = ideal_bedtime_dt
    habitual_bedtime_str: str | None = None
    phase = _habitual_phase(target)
    if phase is not None:
        bh = phase["bedtime_h"]
        # 日付は wake の日を基準にする (通常は target+1、in_progress_night 時は target 自身)。
        wake_date = wake_dt.date()
        if bh >= 0:  # 未明 (例 01:15) → wake と同じ日
            hab_bed = datetime.combine(wake_date, time(0, 0), tz) + timedelta(hours=bh)
        else:  # 前夜 (例 23:00) → wake の前日
            hab_bed = datetime.combine(wake_date - timedelta(days=1), time(0, 0), tz) + timedelta(hours=24 + bh)
        habitual_bedtime_str = hab_bed.strftime("%H:%M")
        if hab_bed > ideal_bedtime_dt + timedelta(minutes=15):
            # 実就寝が理想より遅い → 一気にではなく最大 45 分だけ前倒し (概日前進の限界)
            bedtime_dt = max(ideal_bedtime_dt, hab_bed - timedelta(minutes=MAX_ADVANCE_MIN))
            notes.append(
                f"普段の就寝は約{hab_bed.strftime('%H:%M')}・睡眠{phase['dur_min'] / 60:.1f}h。"
                f"理想{ideal_bedtime_dt.strftime('%H:%M')}へ一気に早めるのは非現実的"
                f"(概日リズムの前進は1日30-60分が限界)。今夜はまず{bedtime_dt.strftime('%H:%M')}を目標に、"
                "毎晩30-45分ずつ前倒しで近づける。"
            )

    sleep_min = int((wake_dt - bedtime_dt).total_seconds() / 60)
    compressed = bedtime_dt > ideal_bedtime_dt + timedelta(minutes=5)
    # 入浴は「上がる」を就寝90分前に置き、そこから逆算して「入る」を出す (湯船に浸かる前提)
    bath_end_dt = bedtime_dt - timedelta(minutes=s.bath_to_bed_lead_min)
    bath_start_dt = bath_end_dt - timedelta(minutes=s.bath_soak_duration_min)
    bath_dt = bath_end_dt  # 後方互換 (= 上がる時刻)

    # 当日のトレーニング終了時刻が bath_dt より遅い場合、現実的な bedtime を再計算
    if last_training_end_jst is not None:
        # 入浴は最短でもトレ後 + 30 分のクールダウン
        earliest_bath = last_training_end_jst + timedelta(minutes=30)
        if earliest_bath > bath_dt:
            bath_dt = earliest_bath
            new_bedtime = bath_dt + timedelta(minutes=s.bath_to_bed_lead_min)
            if new_bedtime > bedtime_dt:
                bedtime_dt = new_bedtime
                actual_sleep = (wake_dt - bedtime_dt).total_seconds() / 60
                if actual_sleep < target_sleep_min:
                    compressed = True
                    sleep_min = int(actual_sleep)
                    notes.append(
                        f"トレーニング終了 ({last_training_end_jst.strftime('%H:%M')}) を考慮すると "
                        f"理想睡眠 {target_sleep_min} 分は確保できません。"
                        f"現実的には {sleep_min} 分程度。"
                    )

    # 目安の就寝時刻をすでに過ぎていて、まだ起床前 (深夜に呼ばれた継続中の夜だけでなく、
    # 単に就寝目標より夜更かししている場合も含む) は「これから今夜の予定を組む」のでは
    # なく「今すぐ寝るべき」局面。目安睡眠を現在時刻起点で再計算し、最優先の note として
    # 先頭に出す。
    sleep_now = bedtime_dt <= now_dt < wake_dt
    if sleep_now:
        sleep_min = max(0, int((wake_dt - now_dt).total_seconds() / 60))
        compressed = True
        notes.insert(
            0,
            f"目安の就寝時刻 ({bedtime_dt.strftime('%H:%M')}) をすでに過ぎています。今すぐ寝てください。"
            f"今から寝れば起床 {wake_dt.strftime('%H:%M')} まで約{sleep_min // 60}h{sleep_min % 60:02d}m 眠れます。",
        )

    # 夕食: 就寝3h前 と「起床+13h(遅すぎない上限)」の早い方を食べ終わりに。遅い夕食を回避。
    healthy_latest = today_wake_dt + timedelta(hours=s.meal_last_h_after_wake)
    dinner_end_dt = min(bedtime_dt - timedelta(minutes=s.dinner_to_bed_lead_min), healthy_latest)
    dinner_start_dt = dinner_end_dt - timedelta(minutes=s.dinner_eat_duration_min)
    dinner_capped_by_clock = healthy_latest < bedtime_dt - timedelta(minutes=s.dinner_to_bed_lead_min)
    if dinner_capped_by_clock:
        notes.append(
            f"夕食は就寝逆算だと {(bedtime_dt - timedelta(minutes=s.dinner_to_bed_lead_min)).strftime('%H:%M')} だが、"
            f"夜遅い食事は代謝に悪いので {dinner_end_dt.strftime('%H:%M')} までに食べ終えるのが理想。"
        )

    # 入浴: トレーニングで bath_dt が後ろ倒しになった場合も「入る→上がる」を再算出
    bath_end_dt = bath_dt
    bath_start_dt = bath_end_dt - timedelta(minutes=s.bath_soak_duration_min)
    notes.append(
        f"入浴は湯船(約{s.bath_temp_c}℃)に{s.bath_soak_duration_min}分。シャワーだけより深部体温が上がり、"
        f"その後の低下で寝つきが良くなる(Haghayegh 2019)。就寝{s.bath_to_bed_lead_min}分前に上がるのが目安。"
    )

    def _win(rec_dt: datetime, minus: int, plus: int) -> dict[str, str]:
        return {
            "rec": rec_dt.strftime("%H:%M"),
            "start": (rec_dt - timedelta(minutes=minus)).strftime("%H:%M"),
            "end": (rec_dt + timedelta(minutes=plus)).strftime("%H:%M"),
        }

    # 推奨範囲: 就寝=目標±20分(規則性) / 起床=目標±30分。夕食・入浴は開始終了の span。
    windows = {
        "bedtime": _win(bedtime_dt, 20, 20),
        "wake": _win(wake_dt, 30, 30),
    }

    # 科学的に大事な timing (厳選): 朝の光浴(概日リズム最強レバー) / カフェイン最終(就寝6h前) /
    # 照明を落とす(就寝2h前、夜光のメラトニン抑制回避)。
    caffeine_cutoff_dt = bedtime_dt - timedelta(hours=s.caffeine_cutoff_hours_before_bed)
    dim_light_dt = bedtime_dt - timedelta(minutes=120)
    morning_light = {
        "start": wake_dt.strftime("%H:%M"),
        "end": (wake_dt + timedelta(minutes=30)).strftime("%H:%M"),
    }

    return {
        "wake": wake_dt.strftime("%H:%M"),
        "bedtime": bedtime_dt.strftime("%H:%M"),  # 今夜の現実的な目標 (習慣から前倒し)
        # bedtime の完全な日時 (TZ-aware ISO)。日付境界 (深夜0時台の呼び出し等) を
        # 正しくまたいだ値なので、他モジュール (wind_down 等) が「就寝まで残り分」を
        # 計算する際は HH:MM を自前で日付に組み立てず、こちらを使うこと。
        "bedtime_iso": bedtime_dt.isoformat(),
        "bath": bath_dt.strftime("%H:%M"),  # 後方互換 (= 上がる時刻)
        "bath_start": bath_start_dt.strftime("%H:%M"),  # 湯船に入る
        "bath_end": bath_end_dt.strftime("%H:%M"),  # 上がる (就寝90分前)
        "bath_method": "湯船",  # シャワーより推奨
        "bath_temp_c": s.bath_temp_c,
        "dinner_cutoff": dinner_end_dt.strftime("%H:%M"),  # 後方互換 (= 食べ終わり)
        "dinner_start": dinner_start_dt.strftime("%H:%M"),  # 食べ始め
        "dinner_end": dinner_end_dt.strftime("%H:%M"),  # 食べ終わり
        "windows": windows,  # bedtime/wake の推奨範囲 + 推奨絶対時刻
        # 科学的に大事な timing (厳選)
        "caffeine_cutoff_time": caffeine_cutoff_dt.strftime("%H:%M"),  # これ以降カフェイン断ち
        "dim_light_time": dim_light_dt.strftime("%H:%M"),  # これ以降 照明↓・ブルーライト減
        "morning_light": morning_light,  # 起床後すぐ屋外光 (概日リズム同調)
        "target_sleep_min": target_sleep_min,
        "estimated_sleep_min": sleep_min,
        "compressed": compressed,
        "sleep_now": sleep_now,  # 目安の就寝時刻をすでに過ぎている (今すぐ寝るべき局面)
        "ideal_bedtime": ideal_bedtime_dt.strftime("%H:%M"),  # 最終目標 (起床−必要睡眠)
        "habitual_bedtime": habitual_bedtime_str,  # 実データの習慣就寝
        "notes": notes,
    }

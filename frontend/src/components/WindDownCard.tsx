import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Moon, Wind, Check, X, Volume2, VolumeX, Smartphone } from "lucide-react";
import { api, type WindDown } from "../lib/api";
import { useWakeLock } from "../lib/wakeLock";
import { primeAudio, tone, haptic, writeMindful } from "../lib/feedback";

/**
 * 就寝前 wind-down。状態から「すぐ寝ろ / 呼吸法 / なし」を出し分ける。
 * さらに **常時アクセスできる呼吸セッションの入口**を置く (状態が none でも手動で開始可)。
 * セッションは全画面・スリープ禁止で、視覚 (円の拡縮) + 音 (サイレント時は無音) +
 * バイブ でフェーズを誘導し、完了で睡眠介入 (breathing) を記録する。
 */
export function WindDownCard() {
  const q = useQuery({ queryKey: ["wind-down"], queryFn: api.windDown, staleTime: 60_000 });
  const [session, setSession] = useState<null | "slow_6" | "cyclic_sigh">(null);
  const d = q.data;

  // 常設の入口。推奨があればその protocol、なければ slow_6 を既定にする。
  const recommended: "slow_6" | "cyclic_sigh" =
    d?.action === "breathe" && d.protocol ? d.protocol : "slow_6";

  return (
    <>
      {/* 状態別の推奨カード */}
      {d?.action === "sleep_now" && (
        <div className="rounded-card border border-info/30 bg-info/[0.06] p-4">
          <div className="flex items-center gap-2 text-info">
            <Moon size={16} strokeWidth={2.2} />
            <span className="text-[13px] font-semibold">{d.headline}</span>
          </div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-ink-dim">{d.reason}</p>
        </div>
      )}
      {d?.action === "breathe" && (
        <div className="rounded-card border border-prog/30 bg-prog/[0.06] p-4">
          <div className="flex items-center gap-2 text-prog">
            <Wind size={16} strokeWidth={2.2} />
            <span className="text-[13px] font-semibold">{d.headline}</span>
          </div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-ink-dim">{d.reason}</p>
          <ol className="mt-3 space-y-1.5">
            {d.steps.map((s, i) => (
              <li key={i} className="flex gap-2 text-[12px] text-ink-dim">
                <span className="telemetry-num text-prog-300">{i + 1}</span>
                <span className="min-w-0 flex-1">{s}</span>
              </li>
            ))}
          </ol>
          <button
            onClick={() => setSession(d.protocol ?? "slow_6")}
            className="press mt-3 w-full rounded-control bg-prog py-2.5 text-[13px] font-semibold text-void"
          >
            {label(d.protocol)}を {d.minutes} 分 はじめる
          </button>
        </div>
      )}

      {/* 常設の呼吸セッション入口 (状態に関わらずいつでも開始できる)。
          id は「就寝前の介入」セクションの案内リンクからのスクロール先として参照される。 */}
      <button
        id="breathe-entry"
        onClick={() => setSession(recommended)}
        className="press flex w-full items-center gap-3 rounded-card border border-hairline bg-hull/50 p-4 text-left"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-prog/15 text-prog">
          <Wind size={18} strokeWidth={2.2} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-semibold text-ink">呼吸で整える</span>
          <span className="block text-[11px] text-ink-faint">
            {label(recommended)} · 円と音とバイブで誘導 (サイレント時は無音)
          </span>
        </span>
        <span className="text-ink-faint">›</span>
      </button>

      {session && (
        <BreatheSession protocol={session} minutes={sessionMinutes(d, session)} onClose={() => setSession(null)} />
      )}
    </>
  );
}

function label(p: "slow_6" | "cyclic_sigh" | null): string {
  return p === "cyclic_sigh" ? "サイクリック・サイ" : "スロー共鳴呼吸";
}

// 推奨に一致する時は推奨分数、そうでなければ既定 (slow_6=6分 / cyclic_sigh=4分)。
function sessionMinutes(d: WindDown | undefined, p: "slow_6" | "cyclic_sigh"): number {
  if (d?.action === "breathe" && d.protocol === p && d.minutes > 0) return d.minutes;
  return p === "cyclic_sigh" ? 4 : 6;
}

// 呼吸フェーズ (秒 + 円の拡大率 + 音の周波数)。臨床固定値:
// slow_6 = 吸4/吐6 (≈6呼吸/分)、cyclic_sigh = 吸2 + 吸い足し1 + 長い呼気5。
const PHASES: Record<string, { label: string; sec: number; scale: number; freq: number; haptic: "light" | "medium" }[]> = {
  slow_6: [
    { label: "吸う", sec: 4, scale: 1, freq: 396, haptic: "medium" },
    { label: "吐く", sec: 6, scale: 0.42, freq: 264, haptic: "light" },
  ],
  cyclic_sigh: [
    { label: "吸う", sec: 2, scale: 0.82, freq: 352, haptic: "light" },
    { label: "もう一吸い", sec: 1, scale: 1, freq: 440, haptic: "medium" },
    { label: "長く吐く", sec: 5, scale: 0.35, freq: 231, haptic: "light" },
  ],
};

/** 全画面の呼吸セッション。視覚+音+バイブでフェーズを誘導。スリープ禁止。完了で記録。 */
function BreatheSession({
  protocol,
  minutes,
  onClose,
}: {
  protocol: "slow_6" | "cyclic_sigh";
  minutes: number;
  onClose: () => void;
}) {
  const phases = PHASES[protocol] ?? PHASES.slow_6;
  const [phaseIdx, setPhaseIdx] = useState(0);
  const [done, setDone] = useState(false);
  const [remaining, setRemaining] = useState(minutes * 60);
  const [soundOn, setSoundOn] = useState(true);
  const [hapticOn, setHapticOn] = useState(true);
  const startedAt = useRef(Date.now());
  const soundRef = useRef(soundOn);
  const hapticRef = useRef(hapticOn);
  soundRef.current = soundOn;
  hapticRef.current = hapticOn;

  useWakeLock(!done);

  // フェーズ送り + そのフェーズの音・バイブを鳴らす。
  useEffect(() => {
    if (done) return;
    const cur = phases[phaseIdx];
    if (soundRef.current) tone(cur.freq);
    if (hapticRef.current) haptic(cur.haptic);
    const t = setTimeout(() => setPhaseIdx((i) => (i + 1) % phases.length), cur.sec * 1000);
    return () => clearTimeout(t);
  }, [phaseIdx, phases, done]);

  // 残り時間 + 自動終了。終了時に睡眠介入 (breathing) を記録。
  useEffect(() => {
    const iv = setInterval(() => {
      const left = minutes * 60 - Math.floor((Date.now() - startedAt.current) / 1000);
      setRemaining(left);
      if (left <= 0) {
        setDone(true);
        api.sleepInterventionSet({ breathing: true }).catch(() => {});
        writeMindful(minutes);
      }
    }, 500);
    return () => clearInterval(iv);
  }, [minutes]);

  const cur = phases[phaseIdx];
  const mm = Math.floor(Math.max(0, remaining) / 60);
  const ss = String(Math.max(0, remaining) % 60).padStart(2, "0");

  return (
    <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-void px-6">
      <div className="absolute right-5 top-[calc(env(safe-area-inset-top)+16px)] flex items-center gap-4">
        <button
          onClick={() => {
            if (!soundOn) primeAudio();
            setSoundOn((v) => !v);
          }}
          aria-label={soundOn ? "音を消す" : "音を出す"}
          className="press text-ink-faint"
        >
          {soundOn ? <Volume2 size={22} /> : <VolumeX size={22} />}
        </button>
        <button
          onClick={() => setHapticOn((v) => !v)}
          aria-label={hapticOn ? "バイブを消す" : "バイブを出す"}
          className={`press ${hapticOn ? "text-ink-faint" : "text-ink-faint/40"}`}
        >
          <Smartphone size={20} />
        </button>
        <button onClick={onClose} aria-label="閉じる" className="press text-ink-faint">
          <X size={24} />
        </button>
      </div>

      {done ? (
        <div className="flex flex-col items-center gap-3 text-center">
          <Check size={40} className="text-prog" strokeWidth={2.4} />
          <p className="text-[16px] font-semibold text-ink">おつかれさま。そのまま眠りへ。</p>
          <p className="max-w-xs text-[12px] leading-relaxed text-ink-faint">
            スマホは置いて、目を閉じて。翌朝の HRV / 安静時心拍が下がっていれば効いています。
            <br />
            今夜の睡眠介入に「呼吸法」を記録しました。
          </p>
          <button
            onClick={onClose}
            className="press mt-2 rounded-control bg-prog px-6 py-2.5 text-[13px] font-semibold text-void"
          >
            終わる
          </button>
        </div>
      ) : (
        <>
          <div className="relative grid h-60 w-60 place-items-center">
            <div
              className="absolute h-60 w-60 rounded-full bg-prog/20"
              style={{ transform: `scale(${cur.scale})`, transition: `transform ${cur.sec}s ease-in-out` }}
            />
            <div className="absolute h-60 w-60 rounded-full border border-prog/40" />
            <div className="relative text-center">
              <div className="text-[24px] font-semibold text-ink">{cur.label}</div>
              <div className="telemetry-num text-[13px] text-ink-faint">{cur.sec}秒</div>
            </div>
          </div>
          <div className="telemetry-num mt-6 text-[14px] text-ink-dim">
            残り {mm}:{ss}
          </div>
          <p className="mt-1 text-[11px] text-ink-faint">画面はつけたままで大丈夫です</p>
        </>
      )}
    </div>
  );
}

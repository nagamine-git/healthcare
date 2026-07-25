import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Flower2, Check, X, Volume2, VolumeX, Smartphone } from "lucide-react";
import { api, type Meditation, type MeditationSegment } from "../lib/api";
import { useWakeLock } from "../lib/wakeLock";
import { primeAudio, tone, haptic, writeMindful } from "../lib/feedback";

/**
 * 就寝前の瞑想 (注意訓練)。WindDownCard (呼吸法) と構造は似せるが演出は意図的に別物にする:
 * - 呼吸ペーサー (円の拡縮) は**出さない**。瞑想は呼吸を操作しないため。
 * - 代わりに「今どこに注意を向けるか」(ボディスキャンの部位 / 呼吸を観る) を大きく表示し、
 *   segments の進行に沿って静かに切り替わる (拍動アニメーションなし)。
 * - 定期的なやさしいベルで注意を再アンカーする。
 * 呼吸法と混同されると n-of-1 (どちらが効いたか) の検証が成立しないため、区別を明示する。
 */
export function MeditationCard() {
  const q = useQuery({ queryKey: ["meditation"], queryFn: api.meditation, staleTime: 60_000 });
  const [session, setSession] = useState<null | "body_scan" | "breath_awareness">(null);
  const d = q.data;

  // 常設の入口。推奨があればその protocol、なければ body_scan を既定にする。
  const recommended: "body_scan" | "breath_awareness" =
    d?.action === "meditate" && d.protocol ? d.protocol : "body_scan";

  const cfg = sessionConfig(d, recommended);

  return (
    <>
      {d?.action === "meditate" && (
        <div className="rounded-card border border-act/30 bg-act/[0.06] p-4">
          <div className="flex items-center gap-2 text-act">
            <Flower2 size={16} strokeWidth={2.2} />
            <span className="text-[13px] font-semibold">{d.headline}</span>
          </div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-ink-dim">{d.reason}</p>
          {d.steps.length > 0 && (
            <ol className="mt-3 space-y-1.5">
              {d.steps.map((s, i) => (
                <li key={i} className="flex gap-2 text-[12px] text-ink-dim">
                  <span className="telemetry-num text-act-300">{i + 1}</span>
                  <span className="min-w-0 flex-1">{s}</span>
                </li>
              ))}
            </ol>
          )}
          <p className="mt-3 text-[11px] leading-relaxed text-ink-faint">
            呼吸は整えません。ただ、いまの注意の向け先を観るだけです。
          </p>
          <button
            onClick={() => setSession(d.protocol ?? "body_scan")}
            className="press mt-3 w-full rounded-control bg-act py-2.5 text-[13px] font-semibold text-void"
          >
            {label(d.protocol)}を {cfg.minutes} 分 はじめる
          </button>
        </div>
      )}

      {/* 常設の瞑想セッション入口 (状態に関わらずいつでも開始できる)。 */}
      <button
        id="meditate-entry"
        onClick={() => setSession(recommended)}
        className="press flex w-full items-center gap-3 rounded-card border border-hairline bg-hull/50 p-4 text-left"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-act/15 text-act">
          <Flower2 size={18} strokeWidth={2.2} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-semibold text-ink">瞑想する</span>
          <span className="block text-[11px] text-ink-faint">
            {label(recommended)} · 呼吸は操作せず、注意の向け先だけを追う (サイレント時は無音)
          </span>
        </span>
        <span className="text-ink-faint">›</span>
      </button>

      {session && (
        <MeditateSession
          protocol={session}
          segments={sessionConfig(d, session).segments}
          bellIntervalSec={sessionConfig(d, session).bellIntervalSec}
          minutes={sessionConfig(d, session).minutes}
          onClose={() => setSession(null)}
        />
      )}
    </>
  );
}

function label(p: "body_scan" | "breath_awareness" | null): string {
  return p === "breath_awareness" ? "呼吸を観る瞑想" : "ボディスキャン";
}

// フォールバック (API 未応答 / action="none" でも常設入口から開始できるようにする既定値)。
// ボディスキャンは部位を順に、呼吸を観る瞑想は単一セグメントで全体を通す。
const FALLBACK_SEGMENTS: Record<"body_scan" | "breath_awareness", MeditationSegment[]> = {
  body_scan: [
    { label: "足の裏", seconds: 45 },
    { label: "ふくらはぎ・すね", seconds: 45 },
    { label: "太もも", seconds: 45 },
    { label: "お腹・腰", seconds: 60 },
    { label: "胸 (呼吸の動き)", seconds: 60 },
    { label: "手・腕", seconds: 45 },
    { label: "肩・首", seconds: 60 },
    { label: "顔・頭", seconds: 60 },
  ],
  breath_awareness: [{ label: "呼吸を観る", seconds: 600 }],
};
const DEFAULT_BELL_INTERVAL_SEC = 90;
// body_scan は部位の切替そのものが注意の再アンカーになるので、フォールバックでも定期ベルは鳴らさない
// (backend scoring/meditation.py の判定と揃える)。breath_awareness は単一セグメントなのでベルを使う。
const FALLBACK_BELL_INTERVAL_SEC: Record<"body_scan" | "breath_awareness", number | null> = {
  body_scan: null,
  breath_awareness: DEFAULT_BELL_INTERVAL_SEC,
};

// 推奨 (d) が今回の protocol と一致し segments を持っていればそれを使う。
// そうでなければ (未確定 / action=none / API未応答) フロント既定のフォールバックを使う。
function sessionConfig(
  d: Meditation | undefined,
  p: "body_scan" | "breath_awareness",
): { segments: MeditationSegment[]; bellIntervalSec: number | null; minutes: number } {
  if (d?.action === "meditate" && d.protocol === p && d.segments.length > 0) {
    const totalSec = d.segments.reduce((sum, s) => sum + s.seconds, 0);
    return { segments: d.segments, bellIntervalSec: d.bell_interval_sec, minutes: Math.max(1, Math.round(totalSec / 60)) };
  }
  const segments = FALLBACK_SEGMENTS[p];
  const totalSec = segments.reduce((sum, s) => sum + s.seconds, 0);
  return {
    segments,
    bellIntervalSec: FALLBACK_BELL_INTERVAL_SEC[p],
    minutes: Math.max(1, Math.round(totalSec / 60)),
  };
}

// 経過秒 elapsed が属するセグメントの index を返す (cumStart[i] = セグメント i の開始秒)。
function segmentIndexAt(cumStart: number[], elapsed: number): number {
  let idx = 0;
  for (let i = 0; i < cumStart.length; i++) {
    if (cumStart[i] <= elapsed) idx = i;
    else break;
  }
  return idx;
}

// やさしいベル。低め・長めの減衰 (呼吸ペーサーの短い誘導音とは違う質感にする)。
const BELL_FREQ = 220;
const BELL_DUR_MS = 1400;

/**
 * 全画面の瞑想セッション。呼吸法 BreatheSession と違い:
 * - 拡縮する円 (呼吸ペーサー) は出さない
 * - 現在の注意対象 (segment.label) を静かに表示するだけ
 * - セグメント切替時 + bellIntervalSec ごとにベルを鳴らして注意を再アンカーする
 */
function MeditateSession({
  protocol,
  segments,
  bellIntervalSec,
  minutes,
  onClose,
}: {
  protocol: "body_scan" | "breath_awareness";
  segments: MeditationSegment[];
  bellIntervalSec: number | null;
  minutes: number;
  onClose: () => void;
}) {
  const totalSec = useMemo(() => segments.reduce((sum, s) => sum + s.seconds, 0), [segments]);
  const cumStart = useMemo(() => {
    const out: number[] = [];
    let acc = 0;
    for (const s of segments) {
      out.push(acc);
      acc += s.seconds;
    }
    return out;
  }, [segments]);

  const [elapsed, setElapsed] = useState(0);
  const [done, setDone] = useState(false);
  const [soundOn, setSoundOn] = useState(true);
  const [hapticOn, setHapticOn] = useState(true);
  const startedAt = useRef(Date.now());
  const soundRef = useRef(soundOn);
  const hapticRef = useRef(hapticOn);
  const segIdxRef = useRef(0);
  const lastBellSecRef = useRef(-1);
  soundRef.current = soundOn;
  hapticRef.current = hapticOn;

  useWakeLock(!done);

  // 経過秒だけを刻む (演出のためのタイマーではなく、進行と完了判定のためだけ)。
  useEffect(() => {
    if (done) return;
    const iv = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt.current) / 1000));
    }, 250);
    return () => clearInterval(iv);
  }, [done]);

  const idx = segmentIndexAt(cumStart, elapsed);
  const cur = segments[Math.max(0, idx)] ?? segments[0];
  const curStart = cumStart[Math.max(0, idx)] ?? 0;
  const curElapsed = Math.min(cur?.seconds ?? 0, Math.max(0, elapsed - curStart));
  const curProgress = cur && cur.seconds > 0 ? curElapsed / cur.seconds : 0;

  // セグメント切替 + 定期ベル + 完了判定。
  useEffect(() => {
    if (done) return;
    if (totalSec > 0 && elapsed >= totalSec) {
      setDone(true);
      api.sleepInterventionSet({ meditation: true }).catch(() => {});
      writeMindful(minutes);
      return;
    }
    const curIdx = Math.max(0, idx);
    let rang = false;
    if (curIdx !== segIdxRef.current) {
      segIdxRef.current = curIdx;
      rang = true;
    } else if (
      bellIntervalSec != null &&
      bellIntervalSec > 0 &&
      elapsed > 0 &&
      elapsed % bellIntervalSec === 0 &&
      lastBellSecRef.current !== elapsed
    ) {
      rang = true;
    }
    if (rang) {
      lastBellSecRef.current = elapsed;
      if (soundRef.current) tone(BELL_FREQ, BELL_DUR_MS);
      if (hapticRef.current) haptic("soft");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elapsed, done, totalSec, bellIntervalSec, minutes]);

  const remaining = Math.max(0, totalSec - elapsed);
  const mm = Math.floor(remaining / 60);
  const ss = String(remaining % 60).padStart(2, "0");

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
          <Check size={40} className="text-act" strokeWidth={2.4} />
          <p className="text-[16px] font-semibold text-ink">おつかれさま。そのまま眠りへ。</p>
          <p className="max-w-xs text-[12px] leading-relaxed text-ink-faint">
            気づいたら思考に流れていても大丈夫。それに気づけたことが実践です。
            <br />
            今夜の睡眠介入に「瞑想」を記録しました。
          </p>
          <button
            onClick={onClose}
            className="press mt-2 rounded-control bg-act px-6 py-2.5 text-[13px] font-semibold text-void"
          >
            終わる
          </button>
        </div>
      ) : (
        <>
          <p className="max-w-xs text-center text-[11px] leading-relaxed text-ink-faint">
            呼吸は整えません。ペースも合わせません。ただ、いまの注意の向け先を観るだけです。
          </p>

          <div className="mt-8 flex flex-col items-center gap-4">
            <span className="text-[11px] uppercase tracking-wide text-ink-faint">
              {protocol === "breath_awareness" ? "呼吸を観る" : "いま注意を向ける場所"}
            </span>
            <div className="text-center text-[28px] font-semibold text-ink">{cur?.label ?? ""}</div>

            {/* 現在セグメントの進捗バー (呼吸ペーサーのような拡縮アニメーションはしない) */}
            <div className="h-1 w-56 overflow-hidden rounded-full bg-hairline/60">
              <div
                className="h-full rounded-full bg-act transition-[width] duration-200 ease-linear"
                style={{ width: `${Math.round(curProgress * 100)}%` }}
              />
            </div>

            {segments.length > 1 && (
              <div className="flex items-center gap-1.5">
                {segments.map((_, i) => (
                  <span
                    key={i}
                    className={`h-1.5 w-1.5 rounded-full ${
                      i === idx ? "bg-act" : i < idx ? "bg-act/40" : "bg-hairline"
                    }`}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="telemetry-num mt-8 text-[14px] text-ink-dim">
            残り {mm}:{ss}
          </div>
          <p className="mt-1 text-[11px] text-ink-faint">
            思考に流れたら、それに気づいて{protocol === "breath_awareness" ? "呼吸" : "いまの場所"}に戻るだけで大丈夫
          </p>
        </>
      )}
    </div>
  );
}

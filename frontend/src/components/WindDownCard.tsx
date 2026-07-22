import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Moon, Wind, Check, X } from "lucide-react";
import { api, type WindDown } from "../lib/api";
import { useWakeLock } from "../lib/wakeLock";

/**
 * 就寝前 wind-down。状態 (睡眠負債・HRV・安静時心拍・カフェイン残量・就寝逆算) から
 * 「すぐ寝ろ」か「この呼吸法を N 分」かを出し分ける。一律に瞑想を勧めない。
 * 呼吸法は全画面の集中セッション (スリープ禁止) で誘導する。
 */
export function WindDownCard() {
  const q = useQuery({ queryKey: ["wind-down"], queryFn: api.windDown, staleTime: 60_000 });
  const [session, setSession] = useState(false);
  const d = q.data;
  if (!d) return null;

  // 落ち着いていて時間もある夜は何も出さない (押し付けない)。
  if (d.action === "none") return null;

  if (d.action === "sleep_now") {
    return (
      <div className="rounded-card border border-info/30 bg-info/[0.06] p-4">
        <div className="flex items-center gap-2 text-info">
          <Moon size={16} strokeWidth={2.2} />
          <span className="text-[13px] font-semibold">{d.headline}</span>
        </div>
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink-dim">{d.reason}</p>
      </div>
    );
  }

  // action === "breathe"
  const label = d.protocol === "cyclic_sigh" ? "サイクリック・サイ" : "スロー共鳴呼吸";
  return (
    <>
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
          onClick={() => setSession(true)}
          className="press mt-3 w-full rounded-control bg-prog py-2.5 text-[13px] font-semibold text-void"
        >
          {label}を {d.minutes} 分 はじめる
        </button>
      </div>
      {session && <BreatheSession d={d} onClose={() => setSession(false)} />}
    </>
  );
}

// 呼吸フェーズ (秒)。臨床固定値: slow_6 = 吸4/吐6 (≈6呼吸/分)、
// cyclic_sigh = 吸2 + 吸い足し1 + 長い呼気5。バックエンド steps と同じ根拠。
const PHASES: Record<string, { label: string; sec: number; scale: number }[]> = {
  slow_6: [
    { label: "吸う", sec: 4, scale: 1 },
    { label: "吐く", sec: 6, scale: 0.42 },
  ],
  cyclic_sigh: [
    { label: "吸う", sec: 2, scale: 0.82 },
    { label: "もう一吸い", sec: 1, scale: 1 },
    { label: "長く吐く", sec: 5, scale: 0.35 },
  ],
};

/** 全画面の呼吸セッション。実行中はスリープ禁止。円の拡縮で吸気/呼気を誘導する。 */
function BreatheSession({ d, onClose }: { d: WindDown; onClose: () => void }) {
  const phases = PHASES[d.protocol ?? "slow_6"] ?? PHASES.slow_6;
  const [phaseIdx, setPhaseIdx] = useState(0);
  const [done, setDone] = useState(false);
  const [remaining, setRemaining] = useState(d.minutes * 60);
  const startedAt = useRef(Date.now());

  // セッション中は画面を消させない (集中を切らさない)。
  useWakeLock(!done);

  useEffect(() => {
    if (done) return;
    const cur = phases[phaseIdx];
    const t = setTimeout(() => setPhaseIdx((i) => (i + 1) % phases.length), cur.sec * 1000);
    return () => clearTimeout(t);
  }, [phaseIdx, phases, done]);

  useEffect(() => {
    const iv = setInterval(() => {
      const left = d.minutes * 60 - Math.floor((Date.now() - startedAt.current) / 1000);
      setRemaining(left);
      if (left <= 0) setDone(true);
    }, 500);
    return () => clearInterval(iv);
  }, [d.minutes]);

  const cur = phases[phaseIdx];
  const mm = Math.floor(Math.max(0, remaining) / 60);
  const ss = String(Math.max(0, remaining) % 60).padStart(2, "0");

  return (
    <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-void px-6">
      <button
        onClick={onClose}
        aria-label="閉じる"
        className="press absolute right-5 top-[calc(env(safe-area-inset-top)+16px)] text-ink-faint"
      >
        <X size={24} />
      </button>

      {done ? (
        <div className="flex flex-col items-center gap-3 text-center">
          <Check size={40} className="text-prog" strokeWidth={2.4} />
          <p className="text-[16px] font-semibold text-ink">おつかれさま。そのまま眠りへ。</p>
          <p className="max-w-xs text-[12px] leading-relaxed text-ink-faint">
            スマホは置いて、目を閉じて。翌朝の HRV / 安静時心拍が下がっていれば効いています。
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
          <div className="relative grid h-56 w-56 place-items-center">
            <div
              className="absolute h-56 w-56 rounded-full bg-prog/20"
              style={{ transform: `scale(${cur.scale})`, transition: `transform ${cur.sec}s ease-in-out` }}
            />
            <div className="absolute h-56 w-56 rounded-full border border-prog/40" />
            <div className="relative text-center">
              <div className="text-[22px] font-semibold text-ink">{cur.label}</div>
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

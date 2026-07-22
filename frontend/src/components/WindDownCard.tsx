import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Moon, Wind, Check } from "lucide-react";
import { api, type WindDown } from "../lib/api";

/**
 * 就寝前 wind-down。状態 (睡眠負債・HRV・安静時心拍・カフェイン残量・就寝逆算) から
 * 「すぐ寝ろ」か「この呼吸法を N 分」かを出し分ける。一律に瞑想を勧めない。
 */
export function WindDownCard() {
  const q = useQuery({ queryKey: ["wind-down"], queryFn: api.windDown, staleTime: 60_000 });
  const d = q.data;
  if (!d) return null;

  // 落ち着いていて時間もある夜は何も出さない (押し付けない)。
  if (d.action === "none") return null;

  if (d.action === "sleep_now") {
    return (
      <div className="rounded-card border border-info/30 bg-info/[0.06] p-4 press">
        <div className="flex items-center gap-2 text-info">
          <Moon size={16} strokeWidth={2.2} />
          <span className="text-[13px] font-semibold">{d.headline}</span>
        </div>
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink-dim">{d.reason}</p>
      </div>
    );
  }

  // action === "breathe"
  return <BreathePanel d={d} />;
}

/** 呼吸プロトコル。円の拡縮でペースを誘導し、完了で HRV の変化を促す。 */
function BreathePanel({ d }: { d: WindDown }) {
  const [running, setRunning] = useState(false);
  const label = d.protocol === "cyclic_sigh" ? "サイクリック・サイ" : "スロー共鳴呼吸";

  return (
    <div className="rounded-card border border-prog/30 bg-prog/[0.06] p-4">
      <div className="flex items-center gap-2 text-prog">
        <Wind size={16} strokeWidth={2.2} />
        <span className="text-[13px] font-semibold">{d.headline}</span>
      </div>
      <p className="mt-1.5 text-[12px] leading-relaxed text-ink-dim">{d.reason}</p>

      {running ? (
        <Pacer protocol={d.protocol} minutes={d.minutes} onStop={() => setRunning(false)} />
      ) : (
        <>
          <ol className="mt-3 space-y-1">
            {d.steps.map((s, i) => (
              <li key={i} className="flex gap-2 text-[12px] text-ink-dim">
                <span className="telemetry-num text-prog-300">{i + 1}</span>
                <span className="min-w-0 flex-1">{s}</span>
              </li>
            ))}
          </ol>
          <button
            onClick={() => setRunning(true)}
            className="press mt-3 w-full rounded-control bg-prog py-2.5 text-[13px] font-semibold text-void"
          >
            {label}を {d.minutes} 分 はじめる
          </button>
        </>
      )}
    </div>
  );
}

// 呼吸フェーズ (秒)。臨床固定値: slow_6 = 吸4/吐6 (≈6呼吸/分)、
// cyclic_sigh = 吸2 + 吸い足し1 + 長い呼気5。バックエンド steps と同じ根拠。
const PHASES: Record<string, { label: string; sec: number; scale: number }[]> = {
  slow_6: [
    { label: "吸う", sec: 4, scale: 1 },
    { label: "吐く", sec: 6, scale: 0.4 },
  ],
  cyclic_sigh: [
    { label: "吸う", sec: 2, scale: 0.8 },
    { label: "もう一吸い", sec: 1, scale: 1 },
    { label: "長く吐く", sec: 5, scale: 0.35 },
  ],
};

/** 円の拡縮で呼吸を誘導するペーサー。指定分で自動終了。 */
function Pacer({
  protocol,
  minutes,
  onStop,
}: {
  protocol: "cyclic_sigh" | "slow_6" | null;
  minutes: number;
  onStop: () => void;
}) {
  const phases = PHASES[protocol ?? "slow_6"] ?? PHASES.slow_6;
  const [phaseIdx, setPhaseIdx] = useState(0);
  const [done, setDone] = useState(false);
  const [remaining, setRemaining] = useState(minutes * 60);
  const startedAt = useRef(Date.now());

  // フェーズ送り (吸う→吐く…)。prefers-reduced-motion でもテキストは進む。
  useEffect(() => {
    if (done) return;
    const cur = phases[phaseIdx];
    const t = setTimeout(() => setPhaseIdx((i) => (i + 1) % phases.length), cur.sec * 1000);
    return () => clearTimeout(t);
  }, [phaseIdx, phases, done]);

  // 残り時間カウントダウン + 自動終了。
  useEffect(() => {
    const iv = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt.current) / 1000);
      const left = minutes * 60 - elapsed;
      setRemaining(left);
      if (left <= 0) setDone(true);
    }, 500);
    return () => clearInterval(iv);
  }, [minutes]);

  if (done) {
    return (
      <div className="mt-3 flex flex-col items-center gap-2 py-4">
        <Check size={28} className="text-prog" strokeWidth={2.4} />
        <p className="text-[13px] font-semibold text-ink">おつかれさま。そのまま眠りへ。</p>
        <p className="text-[11px] text-ink-faint">
          翌朝の HRV / 安静時心拍が下がっていれば効いています。
        </p>
        <button onClick={onStop} className="press mt-1 text-[12px] text-ink-dim underline">
          閉じる
        </button>
      </div>
    );
  }

  const cur = phases[phaseIdx];
  const mm = Math.floor(Math.max(0, remaining) / 60);
  const ss = String(Math.max(0, remaining) % 60).padStart(2, "0");

  return (
    <div className="mt-3 flex flex-col items-center gap-3 py-2">
      <div className="relative grid h-40 w-40 place-items-center">
        {/* 拡縮する円: transition の duration を現フェーズ秒に合わせて呼吸を誘導 */}
        <div
          className="absolute rounded-full bg-prog/25"
          style={{
            width: "10rem",
            height: "10rem",
            transform: `scale(${cur.scale})`,
            transition: `transform ${cur.sec}s ease-in-out`,
          }}
        />
        <div className="absolute h-40 w-40 rounded-full border border-prog/40" />
        <div className="relative text-center">
          <div className="text-[15px] font-semibold text-ink">{cur.label}</div>
          <div className="telemetry-num text-[11px] text-ink-faint">{cur.sec}秒</div>
        </div>
      </div>
      <div className="telemetry-num text-[12px] text-ink-dim">
        残り {mm}:{ss}
      </div>
      <button onClick={onStop} className="press text-[12px] text-ink-faint underline">
        やめる
      </button>
    </div>
  );
}

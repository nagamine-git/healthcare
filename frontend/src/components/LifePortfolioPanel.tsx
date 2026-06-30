import { useQuery } from "@tanstack/react-query";
import { api, type LifePortfolio, type PortfolioHolding } from "../lib/api";
import { kindLabel } from "../lib/labels";
import { Panel, Pill, Skeleton } from "../components/ui/cockpit";

const SIGNAL: Record<PortfolioHolding["signal"], { label: string; tone: "prog" | "act" | "risk" | "neutral" | "info" }> = {
  buy: { label: "投資", tone: "act" },
  hold: { label: "維持", tone: "neutral" },
  funded: { label: "足りてる", tone: "prog" },
  trim: { label: "寄せ過ぎ", tone: "info" },
};

function pct(v: number | null): string {
  return v == null ? "—" : `${Math.round(v)}%`;
}

/** 目標配分(下地)に対する現在配分(塗り)。出遅れ(目標>現在)が伸び代=投資先。 */
function AllocBar({ target, current }: { target: number | null; current: number | null }) {
  const t = target ?? 0;
  const c = current ?? 0;
  return (
    <div className="relative mt-1 h-2 w-full rounded-full bg-hairline">
      {/* 目標配分の位置にマーカー */}
      <div className="absolute top-[-2px] h-3 w-0.5 bg-act-300" style={{ left: `${Math.min(100, t)}%` }} />
      {/* 現在配分の塗り */}
      <div
        className="h-2 rounded-full bg-prog-500"
        style={{ width: `${Math.min(100, c)}%`, transition: "width 500ms ease-out" }}
      />
    </div>
  );
}

function Holding({ h, rank }: { h: PortfolioHolding; rank: number }) {
  const sig = SIGNAL[h.signal];
  return (
    <div className="border-t border-hairline py-2 first:border-t-0">
      <div className="flex items-center gap-2">
        <span className="telemetry-num text-xs text-ink-faint">#{rank}</span>
        <span className="flex-1 text-sm text-ink">{h.label}</span>
        <Pill tone={sig.tone}>{sig.label}</Pill>
        <span className="telemetry-num text-xs text-ink-faint" title="重要度ウェイト">×{h.weight}</span>
      </div>
      <AllocBar target={h.target_alloc} current={h.current_alloc} />
      <div className="mt-0.5 flex justify-between text-[10px] text-ink-faint">
        <span>
          目標配分 <span className="text-act-300">{pct(h.target_alloc)}</span> ・ 現在{" "}
          <span className="text-prog-300">{pct(h.current_alloc)}</span>
        </span>
        <span>現状 {h.level == null ? "—" : Math.round(h.level)}</span>
      </div>
    </div>
  );
}

const MODE: Record<LifePortfolio["mode"], { label: string; cls: string }> = {
  offense: { label: "攻め", cls: "border-prog-700/50 bg-prog-900/15 text-prog-300" },
  neutral: { label: "中立", cls: "border-hairline bg-hull text-ink-dim" },
  defense: { label: "守り", cls: "border-risk/40 bg-risk/10 text-risk" },
};

/** 人生ポートフォリオ: 時間/エネルギーを資本とみなし、投資モード(攻め/守り)× ROI で次の一手を出す。 */
export function LifePortfolioPanel() {
  const q = useQuery({ queryKey: ["life-portfolio"], queryFn: api.lifePortfolio, retry: false });
  if (!q.data) return <Skeleton className="h-48" />;
  const { holdings, top_pick, total_effort, window_days, mode, capacity, directive, mode_reasons } = q.data;
  const m = MODE[mode];
  return (
    <Panel title="人生ポートフォリオ — いま攻める? 守る?" glow="act">
      {/* 投資モード(資本余力ゲート): 余力が乏しい時は投資を控え回復へ */}
      <div className={`rounded-lg border p-2.5 ${m.cls}`}>
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-bold">投資モード: {m.label}</span>
          <span className="telemetry-num text-xs text-ink-faint">
            資本余力 {capacity == null ? "—" : Math.round(capacity)}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-ink-dim">{directive}</p>
        {mode_reasons.length > 0 && (
          <p className="mt-0.5 text-[10px] text-ink-faint">理由: {mode_reasons.join(" / ")}</p>
        )}
      </div>
      {top_pick && (
        <div className="rounded-lg border border-act-700/50 bg-act/10 p-2.5">
          <span className="telemetry-label text-act-300">次の投資先</span>
          <p className="mt-0.5 text-sm font-semibold text-ink">{top_pick.label}</p>
          <p className="text-[11px] text-ink-faint">
            重要度×{top_pick.weight} ・ 伸びしろ {top_pick.gap == null ? "—" : Math.round(top_pick.gap)} ・ 配分が
            目標{pct(top_pick.target_alloc)}に対し現在{pct(top_pick.current_alloc)}
            {top_pick.breach && " ・ 最低ライン割れ"}
            {top_pick.kinds.length > 0 && (
              <> → <span className="text-ink-dim">{top_pick.kinds.slice(0, 3).map(kindLabel).join("・")}</span></>
            )}
          </p>
        </div>
      )}
      <div className="mt-2">
        {holdings.map((h, i) => (
          <Holding key={h.key} h={h} rank={i + 1} />
        ))}
      </div>
      <p className="mt-2 text-[10px] text-ink-faint">
        資産運用と同じ発想: 目標配分(重要度)に対し、直近{window_days}日の行動({total_effort}件)で
        実際どこへ投資したかを比べ、出遅れ×伸びしろが大きい所を「投資」と表示。
      </p>
    </Panel>
  );
}

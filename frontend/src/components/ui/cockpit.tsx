import type { ReactNode } from "react";

type Tone = "prog" | "act" | "risk" | "info" | "neutral";

const TONE_TEXT: Record<Tone, string> = {
  prog: "text-prog-300",
  act: "text-act-300",
  risk: "text-risk",
  info: "text-info-300",
  neutral: "text-ink",
};
const TONE_STROKE: Record<Tone, string> = {
  prog: "#10b981",
  act: "#f59e0b",
  risk: "#fb5b73",
  info: "#38bdf8",
  neutral: "#9fabbd",
};

/** 計器ラベル(小さく・トラッキングの効いた大文字) */
export function Label({ children }: { children: ReactNode }) {
  return <span className="telemetry-label">{children}</span>;
}

/** ロード中のプレースホルダ(レイアウトを保つ)。 */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`shimmer rounded-card ${className}`} />;
}

/** iOS グルーピングカード。glow で計器の微発光を足す。 */
export function Panel({
  title,
  action,
  glow,
  children,
  onClick,
}: {
  title?: string;
  action?: ReactNode;
  glow?: "prog" | "act";
  children: ReactNode;
  onClick?: () => void;
}) {
  const glowCls = glow === "prog" ? "shadow-glow-prog" : glow === "act" ? "shadow-glow-act" : "shadow-card";
  const clickable = onClick
    ? "cursor-pointer transition-all hover:border-white/10 active:scale-[0.995]"
    : "";
  return (
    <section
      onClick={onClick}
      className={`panel-edge rounded-card border border-white/[0.06] bg-hull p-4 ${glowCls} ${clickable}`}
    >
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && <h3 className="text-[13px] font-semibold tracking-tight text-ink">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

/** 大数値テレメトリ。 */
export function Stat({
  label,
  value,
  unit,
  delta,
  tone = "neutral",
  size = "md",
}: {
  label?: string;
  value: ReactNode;
  unit?: string;
  delta?: string | null;
  tone?: Tone;
  size?: "sm" | "md" | "lg";
}) {
  const sizeCls = size === "lg" ? "text-4xl" : size === "sm" ? "text-xl" : "text-2xl";
  return (
    <div className="telemetry-rise">
      <div className={`telemetry-num font-bold ${sizeCls} ${TONE_TEXT[tone]}`}>
        {value}
        {unit && <span className="ml-0.5 text-sm font-medium text-ink-dim">{unit}</span>}
      </div>
      {label && <div className="mt-1 telemetry-label">{label}</div>}
      {delta != null && delta !== "" && <div className="mt-0.5 text-xs text-ink-dim">{delta}</div>}
    </div>
  );
}

export function Button({
  variant = "subtle",
  onClick,
  disabled,
  children,
}: {
  variant?: "primary" | "ghost" | "subtle";
  onClick?: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  const base =
    "press inline-flex items-center justify-center gap-1.5 rounded-control px-3.5 py-2 text-sm font-semibold disabled:opacity-40 disabled:pointer-events-none";
  const v =
    variant === "primary"
      ? "bg-act text-void hover:bg-act-300 shadow-glow-act"
      : variant === "ghost"
        ? "border border-hairline text-ink-dim hover:text-ink hover:border-white/15"
        : "bg-panel text-ink-dim hover:text-ink";
  return (
    <button onClick={onClick} disabled={disabled} className={`${base} ${v}`}>
      {children}
    </button>
  );
}

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  const map: Record<Tone, string> = {
    prog: "bg-prog/15 text-prog-300",
    act: "bg-act/15 text-act-300",
    risk: "bg-risk/15 text-risk",
    info: "bg-info/15 text-info-300",
    neutral: "bg-panel text-ink-dim",
  };
  return (
    <span className={`whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-medium ${map[tone]}`}>
      {children}
    </span>
  );
}

/** リングゲージ(コンディション等 0-100)。中央に大数値。signature の一部。 */
export function RingGauge({
  value,
  label,
  tone = "prog",
  size = 132,
}: {
  value: number | null;
  label?: string;
  tone?: Tone;
  size?: number;
}) {
  const r = (size - 16) / 2;
  const c = 2 * Math.PI * r;
  const frac = value === null ? 0 : Math.max(0, Math.min(1, value / 100));
  const arc = 0.75; // 270° ゲージ
  const dash = c * arc;
  const filled = dash * frac;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-[135deg]">
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke="#222c3b" strokeWidth={9} strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
        />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={TONE_STROKE[tone]} strokeWidth={9} strokeLinecap="round"
          strokeDasharray={`${filled} ${c}`}
          style={{ transition: "stroke-dasharray 700ms cubic-bezier(0.22,1,0.36,1)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`telemetry-num text-4xl font-bold ${TONE_TEXT[tone]}`}>
          {value === null ? "—" : Math.round(value)}
        </span>
        {label && <span className="telemetry-label mt-1">{label}</span>}
      </div>
    </div>
  );
}

/** 横バーゲージ(サブ指標) */
export function BarGauge({ value, label, tone = "prog" }: { value: number | null; label: string; tone?: Tone }) {
  const frac = value === null ? 0 : Math.max(0, Math.min(1, value / 100));
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="telemetry-label">{label}</span>
        <span className={`telemetry-num text-sm font-semibold ${TONE_TEXT[tone]}`}>
          {value === null ? "—" : Math.round(value)}
        </span>
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-hairline">
        <div
          className="h-1.5 rounded-full"
          style={{ width: `${frac * 100}%`, backgroundColor: TONE_STROKE[tone], transition: "width 700ms cubic-bezier(0.22,1,0.36,1)" }}
        />
      </div>
    </div>
  );
}

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
  risk: "#f43f5e",
  info: "#38bdf8",
  neutral: "#9aa7b8",
};

/** 計器ラベル(小さく・トラッキングの効いた大文字) */
export function Label({ children }: { children: ReactNode }) {
  return <span className="telemetry-label">{children}</span>;
}

/** ロード中のプレースホルダ(レイアウトを保つ)。 */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-panel/50 ${className}`} />;
}

/** cockpit カード。glow で計器の微発光を足す。 */
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
  const glowCls = glow === "prog" ? "shadow-glow-prog" : glow === "act" ? "shadow-glow-act" : "";
  const clickable = onClick
    ? "cursor-pointer transition-colors hover:border-ink-faint active:scale-[0.997]"
    : "";
  return (
    <section
      onClick={onClick}
      className={`panel-edge rounded-xl border border-hairline bg-hull p-4 ${glowCls} ${clickable}`}
    >
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between">
          {title && <Label>{title}</Label>}
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
      {label && <div className="mt-0.5 telemetry-label">{label}</div>}
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
    "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-40";
  const v =
    variant === "primary"
      ? "bg-act text-void hover:bg-act-300 shadow-glow-act"
      : variant === "ghost"
        ? "border border-hairline text-ink-dim hover:text-ink hover:border-ink-faint"
        : "bg-panel text-ink-dim hover:text-ink";
  return (
    <button onClick={onClick} disabled={disabled} className={`${base} ${v}`}>
      {children}
    </button>
  );
}

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  const map: Record<Tone, string> = {
    prog: "border-prog-700 text-prog-300",
    act: "border-act-700 text-act-300",
    risk: "border-risk/60 text-risk",
    info: "border-info-700 text-info-300",
    neutral: "border-hairline text-ink-dim",
  };
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] ${map[tone]}`}>{children}</span>
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
          fill="none" stroke="#243044" strokeWidth={8} strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
        />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={TONE_STROKE[tone]} strokeWidth={8} strokeLinecap="round"
          strokeDasharray={`${filled} ${c}`}
          style={{ transition: "stroke-dasharray 600ms ease-out" }}
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
      <div className="mt-1 h-1 rounded-full bg-hairline">
        <div
          className="h-1 rounded-full"
          style={{ width: `${frac * 100}%`, backgroundColor: TONE_STROKE[tone], transition: "width 600ms ease-out" }}
        />
      </div>
    </div>
  );
}

type Props = {
  label: string;
  value: string;
  hint?: string;
};

export function MetricTile({ label, value, hint }: Props) {
  return (
    <div className="rounded-xl bg-hull/70 p-4">
      <div className="text-xs uppercase tracking-wider text-ink-dim">
        {label}
      </div>
      <div className="mt-1 text-2xl font-light tabular-nums text-ink">
        {value}
      </div>
      {hint ? <div className="mt-1 text-xs text-ink-faint">{hint}</div> : null}
    </div>
  );
}

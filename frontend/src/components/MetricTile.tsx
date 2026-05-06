type Props = {
  label: string;
  value: string;
  hint?: string;
};

export function MetricTile({ label, value, hint }: Props) {
  return (
    <div className="rounded-2xl bg-slate-900/70 p-4">
      <div className="text-xs uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className="mt-1 text-2xl font-light tabular-nums text-slate-100">
        {value}
      </div>
      {hint ? <div className="mt-1 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

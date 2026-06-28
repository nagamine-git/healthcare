import type { Focus } from "../lib/api";
import { useCollapse } from "../lib/collapse";

type Props = {
  focus?: Focus;
};

function levelColor(level: Focus["level"]): string {
  if (level === "high") return "text-prog-300";
  if (level === "mid") return "text-act-300";
  if (level === "low") return "text-risk";
  return "text-ink-dim";
}

function levelLabel(level: Focus["level"]): string {
  if (level === "high") return "集中向き";
  if (level === "mid") return "並";
  if (level === "low") return "回復優先";
  return "不明";
}

function barColor(score: number): string {
  if (score >= 70) return "bg-prog-500";
  if (score >= 50) return "bg-act";
  return "bg-risk";
}

export function FocusPanel({ focus }: Props) {
  const [open, setOpen] = useCollapse("focus", false);
  if (!focus) return null;
  const score = focus.score;
  const components = focus.components;

  return (
    <div className="rounded-xl bg-hull/70 p-4 sm:p-6">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <div className="flex items-baseline gap-3">
          <h3 className="text-sm tracking-wider text-ink-dim">
            集中力
            <span className="ml-2 text-[10px] font-normal text-ink-faint">
              いまの状態
            </span>
          </h3>
          <span className="telemetry-num text-3xl tabular-nums text-ink">
            {score == null ? "--" : Math.round(score)}
          </span>
          <span className="text-[10px] text-ink-faint">/100</span>
          <span className={`text-xs ${levelColor(focus.level)}`}>
            {levelLabel(focus.level)}
          </span>
          {!open && focus.peak_windows.length > 0 && (
            <span className="text-[10px] tabular-nums text-prog-300/70">
              ピーク {focus.peak_windows[0].start}–{focus.peak_windows[0].end}
            </span>
          )}
        </div>
        <span className="text-xs text-ink-faint">{open ? "▴" : "▾"}</span>
      </button>

      {!open && (
        <p className="mt-1 text-[11px] leading-relaxed text-ink-faint">
          {focus.rationale}
        </p>
      )}

      {open && (
        <>
          <p className="mt-2 text-xs leading-relaxed text-ink-dim">
            {focus.rationale}
          </p>

          <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-7">
            <Component label="HRV" value={components.hrv} />
            <Component label="エネルギー" value={components.body_battery} />
            <Component label="ストレス" value={components.stress} />
            <Component label="前夜の睡眠" value={components.sleep} />
            <Component label="概日" value={components.circadian} />
            <Component label="大気質" value={components.air_quality ?? null} />
            <Component label="朝の光" value={components.morning_light ?? null} />
          </div>

          {focus.peak_windows.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 text-[10px] uppercase tracking-wider text-ink-faint">
                今日の予測ピーク窓
              </div>
              <ul className="flex flex-wrap gap-2">
                {focus.peak_windows.map((w) => (
                  <li
                    key={`${w.start}-${w.end}`}
                    className="rounded-lg border border-prog/40 bg-prog-500/10 px-2 py-1 telemetry-num text-xs tabular-nums text-prog-300"
                  >
                    {w.start}–{w.end}
                    <span className="ml-2 text-prog-300/70">
                      avg {Math.round(w.avg_score)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {focus.curve.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 flex items-baseline justify-between text-[10px] uppercase tracking-wider text-ink-faint">
                <span>時間別予測 (30 分刻み)</span>
                <span className="normal-case opacity-60">{focus.disclaimer}</span>
              </div>
              <div className="flex items-end gap-[2px] overflow-x-auto pb-1">
                {focus.curve.map((p) => (
                  <div
                    key={p.time}
                    className="flex shrink-0 flex-col items-center"
                    style={{ width: 14 }}
                    title={`${p.time} ${Math.round(p.score)}`}
                  >
                    <div
                      className={`w-full rounded-sm ${barColor(p.score)}`}
                      style={{ height: `${Math.max(4, (p.score / 100) * 48)}px` }}
                    />
                    {p.time.endsWith(":00") && (
                      <span className="mt-1 text-[8px] tabular-nums text-ink-faint">
                        {p.time.split(":")[0]}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Component({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-xl border border-panel bg-hull/40 px-2 py-2">
      <div className="text-[9px] uppercase tracking-wider text-ink-faint">{label}</div>
      <div className="telemetry-num text-sm tabular-nums text-ink">
        {value == null ? "--" : Math.round(value)}
      </div>
    </div>
  );
}

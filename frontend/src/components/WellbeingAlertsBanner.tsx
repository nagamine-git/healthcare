import type { WellbeingAlert } from "../lib/api";

type Props = {
  alerts?: WellbeingAlert[];
};

const STYLE: Record<WellbeingAlert["severity"], string> = {
  critical: "border-risk/70 bg-risk/25 text-risk",
  warning: "border-act-700/60 bg-act-700/20 text-act-300",
  info: "border-act-700/50 bg-act-700/15 text-act-300",
};

const ICON: Record<WellbeingAlert["severity"], string> = {
  critical: "⚠",
  warning: "▲",
  info: "ⓘ",
};

export function WellbeingAlertsBanner({ alerts }: Props) {
  if (!alerts || alerts.length === 0) return null;

  return (
    <div className="space-y-2">
      {alerts.map((a) => (
        <div
          key={a.code}
          className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-xl border px-4 py-3 ${STYLE[a.severity]}`}
        >
          <div className="flex items-baseline gap-2">
            <span className="text-base">{ICON[a.severity]}</span>
            <span className="text-sm font-semibold">{a.title}</span>
          </div>
          <p className="basis-full text-[11px] leading-relaxed opacity-90">
            {a.detail}
          </p>
          <p className="basis-full text-[12px] leading-relaxed">
            <span className="opacity-70">→ </span>
            <span className="font-medium">{a.action}</span>
          </p>
        </div>
      ))}
    </div>
  );
}

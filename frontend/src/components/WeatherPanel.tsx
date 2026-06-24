import { useQuery } from "@tanstack/react-query";
import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSun,
  HelpCircle,
  Shirt,
  Snowflake,
  Sun,
  Umbrella,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import type { WeatherDaily, WeatherHourly, WeatherIcon } from "../lib/api";

const ICONS: Record<WeatherIcon, LucideIcon> = {
  sun: Sun,
  "cloud-sun": CloudSun,
  cloud: Cloud,
  fog: CloudFog,
  drizzle: CloudDrizzle,
  rain: CloudRain,
  snow: Snowflake,
  storm: CloudLightning,
  unknown: HelpCircle,
};
const ICON_COLOR: Record<WeatherIcon, string> = {
  sun: "text-amber-300",
  "cloud-sun": "text-amber-200",
  cloud: "text-slate-300",
  fog: "text-slate-400",
  drizzle: "text-sky-300",
  rain: "text-sky-400",
  snow: "text-cyan-200",
  storm: "text-violet-300",
  unknown: "text-slate-400",
};

function WIcon({ icon, size = 20 }: { icon: WeatherIcon; size?: number }) {
  const C = ICONS[icon] ?? HelpCircle;
  return <C size={size} className={ICON_COLOR[icon] ?? "text-slate-300"} />;
}

const LAUNDRY_STYLE: Record<string, { cls: string; icon: LucideIcon }> = {
  ok: { cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30", icon: Shirt },
  caution: { cls: "bg-amber-500/15 text-amber-300 border-amber-500/30", icon: Umbrella },
  no: { cls: "bg-rose-500/15 text-rose-300 border-rose-500/30", icon: Umbrella },
  unknown: { cls: "bg-slate-700/40 text-slate-400 border-slate-600/40", icon: HelpCircle },
};

function hhmm(iso: string): string {
  return iso.slice(11, 16);
}
function weekday(date: string): string {
  const d = new Date(date + "T00:00:00+09:00");
  return ["日", "月", "火", "水", "木", "金", "土"][d.getDay()];
}

export function WeatherPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["weather"],
    queryFn: () => api.weather(),
    staleTime: 30 * 60 * 1000, // 30分(バックエンドは1hキャッシュ)
  });

  const box = "rounded-xl border border-slate-700/50 bg-slate-800/40 p-4";
  if (isLoading) return <div className={`${box} text-sm text-slate-400`}>天気を読み込み中…</div>;
  if (isError || !data || !data.available) {
    return <div className={`${box} text-sm text-slate-400`}>天気を取得できませんでした</div>;
  }

  const s = data.summary;
  const laundry = s?.laundry;
  const L = laundry ? LAUNDRY_STYLE[laundry.level] : null;

  return (
    <div className={`${box} space-y-4`}>
      {s && (
        <div className="flex items-center gap-3">
          <WIcon icon={s.icon} size={40} />
          <div className="flex-1">
            <div className="text-base font-medium text-slate-100">{s.label}</div>
            <div className="text-sm tabular-nums text-slate-300">
              <span className="text-rose-300">{s.t_max != null ? `${Math.round(s.t_max)}°` : "--"}</span>
              {" / "}
              <span className="text-sky-300">{s.t_min != null ? `${Math.round(s.t_min)}°` : "--"}</span>
              {s.precip_prob_max != null && (
                <span className="ml-2 text-sky-400">☔ {s.precip_prob_max}%</span>
              )}
            </div>
          </div>
          {L && laundry && (
            <div className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${L.cls}`}>
              <L.icon size={14} />
              <span>{laundry.text}</span>
            </div>
          )}
        </div>
      )}

      {data.hourly.length > 0 && (
        <div className="-mx-1 overflow-x-auto px-1">
          <div className="flex gap-3">
            {data.hourly.slice(0, 24).map((h) => (
              <HourCell key={h.time} h={h} />
            ))}
          </div>
        </div>
      )}

      {data.daily.length > 0 && (
        <div className="space-y-1 border-t border-slate-700/40 pt-3">
          {data.daily.map((d, i) => (
            <DayRow key={d.date} d={d} today={i === 0} />
          ))}
        </div>
      )}
    </div>
  );
}

function HourCell({ h }: { h: WeatherHourly }) {
  return (
    <div className="flex w-12 shrink-0 flex-col items-center gap-1 text-center">
      <span className="text-[10px] tabular-nums text-slate-400">{hhmm(h.time)}</span>
      <WIcon icon={h.icon} size={18} />
      <span className="text-xs tabular-nums text-slate-200">
        {h.temp != null ? `${Math.round(h.temp)}°` : "--"}
      </span>
      <span className="text-[10px] tabular-nums text-sky-400">
        {h.precip_prob != null ? `${h.precip_prob}%` : ""}
      </span>
    </div>
  );
}

function DayRow({ d, today }: { d: WeatherDaily; today: boolean }) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className={`w-8 ${today ? "font-medium text-slate-100" : "text-slate-400"}`}>
        {today ? "今日" : weekday(d.date)}
      </span>
      <WIcon icon={d.icon} size={16} />
      <span className="flex-1 text-xs text-slate-300">{d.label}</span>
      <span className="w-12 text-right text-xs tabular-nums text-sky-400">
        {d.precip_prob_max != null ? `${d.precip_prob_max}%` : "--"}
      </span>
      <span className="w-16 text-right tabular-nums">
        <span className="text-rose-300">{d.t_max != null ? `${Math.round(d.t_max)}°` : "--"}</span>
        <span className="text-slate-500">/</span>
        <span className="text-sky-300">{d.t_min != null ? `${Math.round(d.t_min)}°` : "--"}</span>
      </span>
    </div>
  );
}

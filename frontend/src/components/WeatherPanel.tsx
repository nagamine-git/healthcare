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
import type { LaundryAdvice, WeatherDaily, WeatherHourly, WeatherIcon } from "../lib/api";

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

  return (
    <div className={`${box} space-y-4`}>
      {s && (
        <div className="flex items-start gap-3">
          <WIcon icon={s.icon} size={40} />
          <div className="flex-1">
            <div className="text-base font-medium text-slate-100">{s.label}</div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm tabular-nums text-slate-300">
              <span className="whitespace-nowrap">
                <span className="text-rose-300">{s.t_max != null ? `${Math.round(s.t_max)}°` : "--"}</span>
                {" / "}
                <span className="text-sky-300">{s.t_min != null ? `${Math.round(s.t_min)}°` : "--"}</span>
              </span>
              {s.precip_prob_max != null && (
                <span className="whitespace-nowrap text-sky-400">☔ {s.precip_prob_max}%</span>
              )}
              {s.uv_max != null && (
                <span
                  className="whitespace-nowrap"
                  style={{ color: uvColor(s.uv_max) }}
                  title={`UV指数 ${uvLabel(s.uv_max)}`}
                >
                  ☀️ UV {Math.round(s.uv_max)}
                </span>
              )}
              {s.wind && s.wind.speed != null && (
                <span
                  className={`whitespace-nowrap ${
                    s.wind.level === "hazard"
                      ? "text-rose-400"
                      : s.wind.level === "caution"
                        ? "text-amber-300"
                        : "text-slate-400"
                  }`}
                  title="風向・風速(突風)。方角は乾燥効率には影響しません"
                >
                  🍃 {s.wind.dir ?? ""} {Math.round(s.wind.speed)}m/s
                  {s.wind.gust != null && s.wind.gust >= 8 && `(突風${Math.round(s.wind.gust)})`}
                </span>
              )}
            </div>
          </div>
          {laundry && <LaundryBadge laundry={laundry} />}
        </div>
      )}

      {laundry && <LaundryNextLine laundry={laundry} />}

      {data.hourly.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] text-slate-500">
            時間別: 棒の高さ=降水確率 / 色=降水量(濃いほど強い) / 数値は mm
          </div>
          <div className="-mx-1 overflow-x-auto px-1">
            <div className="flex gap-2.5">
              {data.hourly.slice(0, 24).map((h) => (
                <HourCell key={h.time} h={h} />
              ))}
            </div>
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

// UV指数 (WHO 区分) → 色とラベル。乾燥力(日射)の目安にもなる。
function uvColor(uv: number): string {
  if (uv < 3) return "#34d399"; // 弱い
  if (uv < 6) return "#fbbf24"; // 中程度
  if (uv < 8) return "#fb923c"; // 強い
  if (uv < 11) return "#f87171"; // 非常に強い
  return "#c084fc"; // 極端
}
function uvLabel(uv: number): string {
  if (uv < 3) return "弱い";
  if (uv < 6) return "中程度";
  if (uv < 8) return "強い";
  if (uv < 11) return "非常に強い";
  return "極端";
}

function LaundryBadge({ laundry }: { laundry: LaundryAdvice }) {
  const style = LAUNDRY_STYLE[laundry.level] ?? LAUNDRY_STYLE.unknown;
  const Icon = style.icon;
  return (
    <div className="text-right">
      <div
        className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs ${style.cls}`}
      >
        <Icon size={13} />
        <span>{laundry.now_text}</span>
      </div>
      <div className="mt-1 text-[11px] tabular-nums text-slate-400">{laundry.window_text}</div>
    </div>
  );
}

// 次に干せるベストな時刻 (分単位) + 乾く時刻 + 5h(生乾き臭)判定の全幅行。
function LaundryNextLine({ laundry }: { laundry: LaundryAdvice }) {
  const n = laundry.next;
  if (n === undefined) return null; // 旧データ(next 無し)
  if (!n) {
    return (
      <div className="rounded-lg bg-slate-800/40 px-3 py-2 text-[11px] text-slate-400">
        次に干せる好機: 当面なし(雨/日射不足が続く)。室内干し + 除湿/送風を推奨。
      </div>
    );
  }
  const hours = (n.minutes / 60).toFixed(1);
  return (
    <div
      className={`rounded-lg px-3 py-2 text-[11px] leading-relaxed ${
        n.within_5h ? "bg-emerald-900/20 text-emerald-200" : "bg-amber-900/20 text-amber-200"
      }`}
    >
      <span className="font-medium">次の狙い目 {n.start_label}</span>
      <span className="text-slate-400"> に干すと </span>
      <span className="font-medium">{n.dry_by_label} 頃に乾く</span>
      <span className="text-slate-400"> (約{hours}h)</span>
      {!n.within_5h && (
        <span className="ml-1 font-medium">⚠ 5h超=生乾き臭/カビ注意</span>
      )}
      {n.wind_caution && (
        <span className="ml-1 font-medium text-amber-300">・強風注意(しっかり留める)</span>
      )}
    </div>
  );
}

// 降水量(mm) → 棒の色。高さ(確率)とは別に「降ったらどれだけ濡れるか」を色で表す。
function precipColor(mm: number | null): string {
  const m = mm ?? 0;
  if (m < 0.1) return "bg-sky-500/35"; // ほぼ無し(確率だけ)
  if (m < 1) return "bg-sky-400/75"; // 微量
  if (m < 3) return "bg-blue-500"; // 普通の雨
  return "bg-indigo-500"; // 本降り
}

function HourCell({ h }: { h: WeatherHourly }) {
  const prob = h.precip_prob ?? 0;
  return (
    <div className="flex w-10 shrink-0 flex-col items-center gap-1 text-center">
      <span className="text-[10px] tabular-nums text-slate-400">{hhmm(h.time)}</span>
      <WIcon icon={h.icon} size={16} />
      <span className="text-[11px] tabular-nums text-slate-200">
        {h.temp != null ? `${Math.round(h.temp)}°` : "--"}
      </span>
      <div
        className="relative h-12 w-3 overflow-hidden rounded bg-slate-700/40"
        title={
          `降水確率 ${h.precip_prob ?? "?"}% / 降水量 ${h.precip != null ? `${h.precip.toFixed(1)}mm` : "?"}`
        }
      >
        {/* 高さ=降水確率、色=降水量の強さ */}
        <div
          className={`absolute inset-x-0 bottom-0 ${precipColor(h.precip)}`}
          style={{ height: `${Math.max(prob, 3)}%` }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-sky-300">
        {h.precip_prob != null ? `${h.precip_prob}%` : "--"}
      </span>
      <span className="h-3 text-[9px] tabular-nums text-sky-400/70">
        {h.precip != null && h.precip > 0 ? `${h.precip.toFixed(1)}mm` : ""}
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

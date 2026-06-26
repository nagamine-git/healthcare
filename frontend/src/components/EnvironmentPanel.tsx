import type { AirQuality, MorningLight, Pressure } from "../lib/api";
import { useCollapse } from "../lib/collapse";

type GeoControls = {
  coords: {
    lat: number;
    lon: number;
    accuracy: number | null;
    obtained_at: number;
  } | null;
  busy: boolean;
  error: string | null;
  denied: boolean;
  onRequest: () => void;
  onClear: () => void;
};

type Props = {
  pressure?: Pressure | null;
  airQuality?: AirQuality | null;
  morningLight?: MorningLight;
  geo?: GeoControls;
};

const PRESSURE_STYLE: Record<Pressure["risk_level"], string> = {
  calm: "border-emerald-700/40 bg-emerald-900/10 text-emerald-200",
  watch: "border-amber-700/50 bg-amber-900/15 text-amber-200",
  warning: "border-orange-700/60 bg-orange-900/20 text-orange-200",
  severe: "border-rose-700/70 bg-rose-900/30 text-rose-100",
};
const PRESSURE_LABEL: Record<Pressure["risk_level"], string> = {
  calm: "安定",
  watch: "注意",
  warning: "警戒",
  severe: "危険",
};

const AIR_STYLE: Record<AirQuality["risk_level"], string> = {
  good: "border-emerald-700/40 bg-emerald-900/10 text-emerald-200",
  moderate: "border-amber-700/50 bg-amber-900/15 text-amber-200",
  unhealthy_sensitive: "border-orange-700/60 bg-orange-900/20 text-orange-200",
  unhealthy: "border-rose-700/70 bg-rose-900/30 text-rose-100",
};
const AIR_LABEL: Record<AirQuality["risk_level"], string> = {
  good: "良好",
  moderate: "普通",
  unhealthy_sensitive: "敏感層注意",
  unhealthy: "汚染",
};

export function EnvironmentPanel({
  pressure,
  airQuality,
  morningLight,
  geo,
}: Props) {
  // 重要度の高い環境状態 (warning/severe / unhealthy) があればデフォルト開
  const hasAlert =
    (pressure && (pressure.risk_level === "warning" || pressure.risk_level === "severe")) ||
    (airQuality &&
      (airQuality.risk_level === "unhealthy" ||
        airQuality.risk_level === "unhealthy_sensitive"));
  const [open, setOpen] = useCollapse("environment", !!hasAlert);

  if (!pressure && !airQuality && !morningLight) return null;

  return (
    <div className="rounded-2xl bg-slate-900/70 p-4 sm:p-6">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <div className="flex flex-wrap items-baseline gap-3">
          <h3 className="text-sm tracking-wider text-slate-300">環境</h3>
          {pressure && (
            <span className="font-mono text-xs tabular-nums text-slate-400">
              {pressure.current_hpa?.toFixed(0)} hPa
              {pressure.delta_24h_hpa != null &&
                ` (${fmtDelta(pressure.delta_24h_hpa)})`}
            </span>
          )}
          {airQuality && airQuality.pm2_5 != null && (
            <span className="font-mono text-xs tabular-nums text-slate-400">
              PM2.5 {airQuality.pm2_5.toFixed(0)}
            </span>
          )}
          {morningLight && morningLight.score != null && (
            <span className="font-mono text-xs tabular-nums text-slate-400">
              朝光 {Math.round(morningLight.score)}
            </span>
          )}
          {hasAlert && !open && (
            <span className="rounded border border-orange-500/60 bg-orange-900/30 px-1.5 py-0.5 text-[10px] text-orange-200">
              要注意
            </span>
          )}
        </div>
        <span className="text-xs text-slate-500">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div className="mt-3">
          {geo && (
            <div className="mb-2">
              <GeoControlsRow geo={geo} />
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            {pressure && <PressureCard pressure={pressure} />}
            {airQuality && <AirCard air={airQuality} />}
          </div>
          {morningLight && <MorningLightCard light={morningLight} />}
        </div>
      )}
    </div>
  );
}

function PressureCard({ pressure }: { pressure: Pressure }) {
  return (
    <div className={`min-w-0 rounded-xl border p-3 ${PRESSURE_STYLE[pressure.risk_level]}`}>
      <div className="flex items-baseline justify-between gap-1">
        <span className="truncate text-[10px] uppercase tracking-wider opacity-70">
          気圧 ({pressure.location_label})
        </span>
        <span className="rounded border border-current/40 px-2 py-0.5 text-[10px] tracking-wider">
          {PRESSURE_LABEL[pressure.risk_level]}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-1.5">
        <span className="font-mono text-2xl tabular-nums">
          {pressure.current_hpa?.toFixed(1) ?? "--"}
        </span>
        <span className="whitespace-nowrap text-xs opacity-60">hPa</span>
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono text-[10px] tabular-nums opacity-80">
        {pressure.delta_24h_hpa != null && (
          <span>24h {fmtDelta(pressure.delta_24h_hpa)}</span>
        )}
        {pressure.delta_6h_hpa != null && (
          <span>6h {fmtDelta(pressure.delta_6h_hpa)}</span>
        )}
        {pressure.forecast_delta_24h_hpa != null && (
          <span>+24h {fmtDelta(pressure.forecast_delta_24h_hpa)}</span>
        )}
      </div>
      <p className="mt-1 text-[11px] leading-relaxed opacity-90">
        {pressure.risk_reason}
      </p>
      {pressure.series.length > 0 && <PressureSeries series={pressure.series} />}
    </div>
  );
}

function AirCard({ air }: { air: AirQuality }) {
  return (
    <div className={`min-w-0 rounded-xl border p-3 ${AIR_STYLE[air.risk_level]}`}>
      <div className="flex items-baseline justify-between gap-1">
        <span className="truncate text-[10px] uppercase tracking-wider opacity-70">
          大気質 ({air.location_label})
        </span>
        <span className="rounded border border-current/40 px-2 py-0.5 text-[10px] tracking-wider">
          {AIR_LABEL[air.risk_level]}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-1.5">
        <span className="font-mono text-2xl tabular-nums">
          {air.pm2_5?.toFixed(1) ?? "--"}
        </span>
        <span className="whitespace-nowrap text-[10px] opacity-60">μg/m³ (PM2.5)</span>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 font-mono text-[10px] tabular-nums opacity-80">
        {air.aqi != null && <span>AQI {air.aqi}</span>}
        {air.uv_index != null && <span>UV {air.uv_index.toFixed(1)}</span>}
        {air.o3 != null && <span>O₃ {air.o3.toFixed(0)}</span>}
        {air.no2 != null && <span>NO₂ {air.no2.toFixed(0)}</span>}
        {air.pm10 != null && <span>PM10 {air.pm10.toFixed(0)}</span>}
      </div>
      <p className="mt-1 text-[11px] leading-relaxed opacity-90">
        {air.risk_reason}
      </p>
    </div>
  );
}

function MorningLightCard({ light }: { light: MorningLight }) {
  const score = light.score;
  const tone =
    score == null
      ? "border-slate-700/40 bg-slate-900/30 text-slate-400"
      : score >= 80
      ? "border-emerald-700/40 bg-emerald-900/10 text-emerald-200"
      : score >= 50
      ? "border-amber-700/50 bg-amber-900/15 text-amber-200"
      : "border-rose-700/60 bg-rose-900/20 text-rose-200";
  return (
    <div className={`mt-3 rounded-xl border p-3 ${tone}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wider opacity-70">
          朝の光暴露 ({light.window_start_jst}〜{light.window_end_jst})
        </span>
        <span className="font-mono text-[10px] tabular-nums opacity-80">
          {light.daylight_min != null
            ? `日光 ${light.daylight_min} 分`
            : `${light.steps_in_window} 歩 (推定)`}
        </span>
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="font-mono text-2xl tabular-nums">
          {score == null ? "--" : Math.round(score)}
        </span>
        <span className="text-xs opacity-60">/100</span>
      </div>
      <p className="mt-1 text-[11px] leading-relaxed opacity-90">
        {light.rationale}
      </p>
    </div>
  );
}

function GeoControlsRow({ geo }: { geo: GeoControls }) {
  const c = geo.coords;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
      {c ? (
        <>
          <span className="font-mono tabular-nums">
            GPS {c.lat.toFixed(3)}, {c.lon.toFixed(3)}
            {c.accuracy != null && ` (±${Math.round(c.accuracy)}m)`}
          </span>
          <button
            onClick={geo.onRequest}
            disabled={geo.busy}
            className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800 disabled:opacity-30"
          >
            {geo.busy ? "..." : "更新"}
          </button>
          <button
            onClick={geo.onClear}
            className="rounded border border-slate-700 px-2 py-0.5 opacity-70 hover:opacity-100"
            title="GPS をクリアして config 座標に戻す"
          >
            ×
          </button>
        </>
      ) : (
        <>
          <span>
            {geo.denied ? "GPS 拒否中" : "config 座標を使用中"}
          </span>
          <button
            onClick={geo.onRequest}
            disabled={geo.busy}
            className="rounded border border-amber-700/60 bg-amber-900/20 px-2 py-0.5 text-amber-200 hover:bg-amber-900/40 disabled:opacity-30"
          >
            {geo.busy ? "..." : "GPS で取得"}
          </button>
        </>
      )}
      {geo.error && (
        <span className="basis-full text-[10px] opacity-60">{geo.error}</span>
      )}
    </div>
  );
}

function fmtDelta(d: number): string {
  const s = d >= 0 ? `+${d.toFixed(1)}` : d.toFixed(1);
  return `${s}`;
}

function PressureSeries({ series }: { series: Pressure["series"] }) {
  if (series.length === 0) return null;
  const values = series.map((p) => p.hpa);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  const midIdx = Math.floor(series.length / 2);
  return (
    <div className="mt-2">
      <div className="flex h-10 items-end gap-[2px] overflow-x-auto pb-1">
        {series.map((p, i) => {
          const h = Math.max(2, ((p.hpa - min) / range) * 36);
          const isFuture = i > midIdx;
          return (
            <div
              key={p.time}
              className="flex shrink-0 flex-col items-center"
              style={{ width: 5 }}
              title={`${p.time}: ${p.hpa.toFixed(1)} hPa`}
            >
              <div
                className={`w-full rounded-sm ${
                  isFuture ? "bg-current opacity-50" : "bg-current opacity-90"
                }`}
                style={{ height: `${h}px` }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-0.5 flex justify-between text-[9px] tabular-nums opacity-50">
        <span>-24h</span>
        <span>現在</span>
        <span>+24h</span>
      </div>
    </div>
  );
}

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, SlidersHorizontal } from "lucide-react";
import { api } from "../lib/api";
import { achState } from "../lib/achievement";
import type { LifeDomain } from "../lib/api";

function barColor(ach: number | null): string {
  // 閾値は lib/achievement に一元化 (StatusLamps と共有)
  switch (achState(ach)) {
    case "good": return "bg-emerald-500";
    case "warn": return "bg-amber-500";
    case "bad": return "bg-rose-500";
    default: return "bg-slate-700";
  }
}

/** "2026-01-04" → "1/4 (152日前)" */
function staleLabel(lastDataAt: string | null): string {
  if (!lastDataAt) return "データ未受信";
  const last = new Date(lastDataAt);
  const days = Math.floor((Date.now() - last.getTime()) / 86_400_000);
  return `最終データ ${last.getMonth() + 1}/${last.getDate()} (${days}日前)`;
}

function DomainRow({
  domain,
  showSlider,
  onWeight,
}: {
  domain: LifeDomain;
  showSlider: boolean;
  onWeight: (w: number) => void;
}) {
  const ach = domain.achievement;
  return (
    <div className="rounded-xl bg-slate-900/70 p-3">
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-slate-200">{domain.label}</span>
        <span className="text-lg font-light tabular-nums text-slate-100">
          {ach != null ? Math.round(ach) : "--"}
        </span>
      </div>
      {domain.detail && <div className="text-[10px] text-slate-500">{domain.detail}</div>}
      {domain.stale && domain.weight > 0 && (
        <div className="text-[10px] text-amber-400">⚠ {staleLabel(domain.last_data_at)}</div>
      )}
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full ${barColor(ach)}`} style={{ width: `${ach ?? 0}%` }} />
      </div>
      {showSlider && (
        <div className="mt-2 flex items-center gap-2">
          <span className="text-[10px] text-slate-500">重み</span>
          <input
            type="range"
            min={0}
            max={3}
            step={0.5}
            value={domain.weight}
            onChange={(e) => onWeight(parseFloat(e.target.value))}
            className="flex-1 accent-emerald-500"
          />
          <span className="w-8 text-right text-[10px] tabular-nums text-slate-400">
            {domain.weight.toFixed(1)}
          </span>
        </div>
      )}
    </div>
  );
}

export function LifeSection() {
  const qc = useQueryClient();
  const [editWeights, setEditWeights] = useState(false);
  const life = useQuery({ queryKey: ["life"], queryFn: api.life });
  const setWeights = useMutation({
    mutationFn: (weights: Record<string, number>) => api.setLifeWeights(weights),
    onSuccess: (data) => qc.setQueryData(["life"], data),
  });
  const applyPreset = useMutation({
    mutationFn: (name: string) => api.applyLifePreset(name),
    onSuccess: (data) => qc.setQueryData(["life"], data),
  });

  const data = life.data;

  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wider text-slate-400">
          理想への総合接近度
        </span>
        <span className="flex items-baseline gap-2">
          {data?.coverage && data.coverage.active < data.coverage.total && (
            <span className="text-[10px] tabular-nums text-amber-400/80"
                  title="達成度データがあるドメイン数。少ないほどライフスコアは一部のドメインだけの平均になる">
              記録 {data.coverage.active}/{data.coverage.total}
            </span>
          )}
          <span className="text-3xl font-light tabular-nums text-emerald-300">
            {data?.life_score != null ? Math.round(data.life_score) : "--"}
          </span>
        </span>
      </div>

      {/* 重み調整 (プリセット + スライダー) は普段使わないので開閉式・既定で閉 */}
      <button
        type="button"
        onClick={() => setEditWeights(!editWeights)}
        aria-expanded={editWeights}
        className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-slate-300"
      >
        {editWeights ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <SlidersHorizontal size={12} />
        重み調整 (期待水準)
      </button>

      {editWeights && data && (
        <div className="flex flex-wrap gap-1.5">
          {data.presets.map((p) => (
            <button
              key={p.key}
              onClick={() => applyPreset.mutate(p.key)}
              className="rounded-full bg-slate-800/70 px-3 py-1 text-[11px] text-slate-300 hover:bg-slate-700"
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {life.isLoading ? (
        <div className="text-sm text-slate-400">読み込み中...</div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {data?.domains
            .slice()
            // 重み (重要度) 降順 → データありを先 → 達成度が低い順 (要テコ入れが上)
            .sort((a, b) => {
              if (b.weight !== a.weight) return b.weight - a.weight;
              const aNull = a.achievement == null ? 1 : 0;
              const bNull = b.achievement == null ? 1 : 0;
              if (aNull !== bNull) return aNull - bNull;
              return (a.achievement ?? 0) - (b.achievement ?? 0);
            })
            .map((d) => (
            <DomainRow
              key={d.key}
              domain={d}
              showSlider={editWeights}
              onWeight={(w) => {
                const weights: Record<string, number> = {};
                for (const dd of data.domains) weights[dd.key] = dd.key === d.key ? w : dd.weight;
                setWeights.mutate(weights);
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}

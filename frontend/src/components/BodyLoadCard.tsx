import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Dumbbell, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "../lib/api";
import type { BodyGroup } from "../lib/api";

/**
 * 部位別 (5 機能群) の刺激・回復・週間負荷カード。
 *
 * データは Garmin の activity から完全自動で導出 (手動入力なし)。
 * 「今日やるべき部位」= 回復済み × 美的重み (V字なら肩・背中を重視) × 直近負荷少。
 * 強度を確証できない群 (種目情報なしの cardio/HIIT 由来) は confidence で薄く表示し、
 * 「刺激記録なし=伸びしろ」も正直に出す。
 */

function recoveryColor(pct: number): string {
  if (pct >= 100) return "bg-emerald-500";
  if (pct >= 60) return "bg-amber-500";
  return "bg-rose-500";
}

function ConfBadge({ c }: { c: BodyGroup["confidence"] }) {
  if (c === "measured")
    return <span className="text-[9px] text-emerald-400" title="種目記録から実測">実測</span>;
  if (c === "inferred")
    return <span className="text-[9px] text-slate-500" title="活動種別からの推定 (強度は概算)">推定</span>;
  return <span className="text-[9px] text-slate-600" title="刺激の記録なし">記録なし</span>;
}

function GroupRow({ g }: { g: BodyGroup }) {
  const ready = g.recovery_pct >= 100;
  const sore = g.recovery_pct < 60;
  return (
    <div className={`rounded-md px-2 py-1.5 ${g.confidence === "none" ? "opacity-70" : ""}`}>
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="min-w-0 flex-1 truncate text-slate-200">{g.label}</span>
        <ConfBadge c={g.confidence} />
        <span className="shrink-0 tabular-nums text-slate-500">
          {g.confidence === "none"
            ? "刺激なし"
            : ready
              ? "回復済"
              : `回復${g.recovery_pct}%`}
        </span>
      </div>
      {/* 回復バー */}
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full ${recoveryColor(g.recovery_pct)} transition-all`}
          style={{ width: `${Math.max(g.recovery_pct, 3)}%` }} />
      </div>
      <div className="mt-0.5 flex items-baseline justify-between text-[9px] text-slate-500">
        <span>{g.home}</span>
        <span className="shrink-0 tabular-nums">
          {g.confidence === "none"
            ? "伸びしろ"
            : sore
              ? "回復待ち"
              : `週負荷 ${Math.round(g.week_load)}`}
        </span>
      </div>
    </div>
  );
}

export function BodyLoadCard() {
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["bodyload"], queryFn: api.bodyLoad });

  if (q.isLoading || !q.data) {
    return (
      <section className="space-y-2 rounded-2xl bg-slate-900/40 p-4">
        <span className="text-xs text-slate-500">部位別の負荷を計算中…</span>
      </section>
    );
  }
  const s = q.data;
  // 優先度順 (今日やるべき部位が上)
  const ordered = [...s.groups].sort((a, b) => b.priority - a.priority);
  const sug = s.suggestion;

  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center gap-1.5">
        <Dumbbell size={14} className="text-amber-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">部位別トレーニング</span>
        <span className="ml-auto text-[10px] text-slate-500">
          {s.confidence === "high" ? "精度 高 (種目記録あり)" : s.confidence === "low" ? "精度 低 (活動種別から推定)" : "活動記録待ち"}
        </span>
      </div>

      {/* 今日やるべき部位 */}
      {sug.length > 0 && (
        <div className="rounded-xl bg-slate-900/60 p-2.5">
          <div className="mb-1 text-[11px] text-slate-300">今日やるべき部位</div>
          <div className="flex flex-col gap-1.5">
            {sug.map((x) => (
              <div key={x.key} className="flex items-baseline gap-2 text-[12px]">
                <span className="shrink-0 font-semibold text-amber-300">{x.label}</span>
                {x.confidence === "none" && (
                  <span className="shrink-0 text-[9px] text-slate-500">伸びしろ (刺激記録なし)</span>
                )}
                <span className="min-w-0 flex-1 truncate text-[10px] text-slate-400">{x.home}</span>
              </div>
            ))}
          </div>
          <p className="mt-1.5 text-[9px] text-slate-500">
            魅力的な肉体 (V字=肩幅:ウエスト) には肩・背中が最優先。Garmin の活動から自動算出 — 背中(引く)は自重だと検出されにくく「伸びしろ」に出やすい。
          </p>
        </div>
      )}

      {/* 部位別の回復・負荷 */}
      <div className="grid gap-0.5">
        {(open ? ordered : ordered.slice(0, 3)).map((g) => (
          <GroupRow key={g.key} g={g} />
        ))}
      </div>

      <button type="button" onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-0.5 text-[10px] text-slate-500 hover:text-slate-300">
        {open ? <><ChevronUp size={11} /> 折りたたむ</> : <><ChevronDown size={11} /> 全{s.groups.length}部位を表示</>}
      </button>
    </section>
  );
}

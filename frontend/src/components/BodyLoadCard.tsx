import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Dumbbell, HeartPulse } from "lucide-react";
import { api } from "../lib/api";
import type { BodyMapMuscle, BodyHpGauge } from "../lib/api";
import { BodyFigure } from "./BodyFigure";
import type { ShapeKey } from "./BodyFigure";

/**
 * 部位別の筋負荷マップ + 統合ステータス (Tarkov 風 HP ゲージ)。
 *
 * データは Garmin の activity / Body Battery / 偏頭痛 / 水分から完全自動で導出。
 * 筋負荷: 緑=回復済み(やれる) / 橙→赤=直近に負荷(回復中)。おすすめ部位は枠で強調。
 * 統合: 緑=良好 / 赤=要注意。各ゲージは実指標の裏付けつき。
 */

// 回復% → 色 (高=回復済み=緑 / 低=直近に負荷=赤)
function recoveryColor(pct: number, conf: string): string {
  if (conf === "none") return "#475569";
  if (pct >= 90) return "#34d399";
  if (pct >= 60) return "#fbbf24";
  return "#f87171";
}
// HP値 → 色 (高=良好=緑 / 低=要注意=赤)
function hpColor(v: number | null): string {
  if (v == null) return "#475569";
  if (v >= 70) return "#34d399";
  if (v >= 40) return "#fbbf24";
  return "#f87171";
}

const MUSCLE_FRONT: Record<string, ShapeKey[]> = {
  shoulders: ["shoulderL", "shoulderR"],
  push: ["chest"],
  core: ["abs"],
  legs: ["legL", "legR"],
};
const MUSCLE_BACK: Record<string, ShapeKey[]> = {
  shoulders: ["shoulderL", "shoulderR"],
  pull: ["upperBack"],
  legs: ["legL", "legR"],
};
const HP_SHAPES: Record<string, ShapeKey[]> = {
  head: ["head"],
  thorax: ["chest"],
  stomach: ["abs"],
  arm: ["armL", "armR"],
  leg: ["legL", "legR"],
};

function buildFills(
  map: Record<string, ShapeKey[]>,
  colorOf: (key: string) => string,
  suggestedKeys?: Set<string>,
): { fills: Partial<Record<ShapeKey, string>>; suggested: Partial<Record<ShapeKey, boolean>> } {
  const fills: Partial<Record<ShapeKey, string>> = {};
  const suggested: Partial<Record<ShapeKey, boolean>> = {};
  for (const [key, shapes] of Object.entries(map)) {
    for (const sh of shapes) {
      fills[sh] = colorOf(key);
      if (suggestedKeys?.has(key)) suggested[sh] = true;
    }
  }
  return { fills, suggested };
}

function MuscleRow({ m }: { m: BodyMapMuscle }) {
  const ready = m.recovery_pct >= 100;
  return (
    <div className={`rounded-md px-2 py-1.5 ${m.confidence === "none" ? "opacity-70" : ""} ${m.suggested ? "bg-amber-500/5" : ""}`}>
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="min-w-0 flex-1 truncate text-slate-200">
          {m.label}
          {m.suggested && <span className="ml-1 text-[9px] text-amber-300">★今日</span>}
        </span>
        <span className="shrink-0 tabular-nums text-slate-500">
          {m.confidence === "none" ? "刺激なし" : ready ? "回復済" : `回復${m.recovery_pct}%`}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className="h-full rounded-full transition-all"
          style={{ width: `${Math.max(m.recovery_pct, 3)}%`, background: recoveryColor(m.recovery_pct, m.confidence) }} />
      </div>
      <div className="mt-0.5 truncate text-[9px] text-slate-500">{m.confidence === "none" ? `伸びしろ · ${m.home}` : m.home}</div>
    </div>
  );
}

function HpRow({ g }: { g: BodyHpGauge }) {
  return (
    <div className="rounded-md px-2 py-1.5">
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="shrink-0 text-slate-200">{g.label}</span>
        <span className="min-w-0 flex-1 truncate text-[10px] text-slate-500">{g.metric}</span>
        <span className="shrink-0 tabular-nums" style={{ color: hpColor(g.value) }}>
          {g.value == null ? "—" : g.value}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className="h-full rounded-full transition-all"
          style={{ width: `${Math.max(g.value ?? 0, 3)}%`, background: hpColor(g.value) }} />
      </div>
      <div className="mt-0.5 truncate text-[9px] text-slate-500">{g.detail}</div>
    </div>
  );
}

export function BodyLoadCard() {
  const [tab, setTab] = useState<"muscle" | "hp">("muscle");
  const q = useQuery({ queryKey: ["bodymap"], queryFn: api.bodyMap });

  if (q.isLoading || !q.data) {
    return (
      <section className="space-y-2 rounded-2xl bg-slate-900/40 p-4">
        <span className="text-xs text-slate-500">部位別の負荷を計算中…</span>
      </section>
    );
  }
  const s = q.data;
  const muscleByKey = (key: string) => s.muscle.find((m) => m.key === key);
  const suggestedKeys = new Set(s.suggestion.map((x) => x.key));

  const muscleColor = (key: string) => {
    const m = muscleByKey(key);
    return m ? recoveryColor(m.recovery_pct, m.confidence) : "#475569";
  };
  const front = buildFills(MUSCLE_FRONT, muscleColor, suggestedKeys);
  const back = buildFills(MUSCLE_BACK, muscleColor, suggestedKeys);

  const hpByRegion = (r: string) => s.hp.find((g) => g.region === r);
  const hpColorOf = (r: string) => hpColor(hpByRegion(r)?.value ?? null);
  const hpFig = buildFills(HP_SHAPES, hpColorOf);

  const orderedMuscle = [...s.muscle].sort((a, b) => Number(b.suggested) - Number(a.suggested) || a.recovery_pct - b.recovery_pct);

  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center gap-1.5">
        <Dumbbell size={14} className="text-amber-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">部位別ステータス</span>
        {/* タブ */}
        <span className="ml-auto flex gap-1 rounded-lg bg-slate-800/80 p-0.5 text-[10px]">
          <button type="button" onClick={() => setTab("muscle")}
            className={`flex items-center gap-1 rounded-md px-2 py-1 ${tab === "muscle" ? "bg-slate-700 text-amber-200" : "text-slate-400"}`}>
            <Dumbbell size={11} /> 筋負荷
          </button>
          <button type="button" onClick={() => setTab("hp")}
            className={`flex items-center gap-1 rounded-md px-2 py-1 ${tab === "hp" ? "bg-slate-700 text-emerald-200" : "text-slate-400"}`}>
            <HeartPulse size={11} /> 統合
          </button>
        </span>
      </div>

      {tab === "muscle" ? (
        <>
          <div className="flex items-start justify-center gap-6 rounded-xl bg-slate-900/60 py-2">
            <div className="flex flex-col items-center">
              <BodyFigure fills={front.fills} suggested={front.suggested} />
              <span className="mt-0.5 text-[9px] text-slate-500">前面</span>
            </div>
            <div className="flex flex-col items-center">
              <BodyFigure fills={back.fills} suggested={back.suggested} />
              <span className="mt-0.5 text-[9px] text-slate-500">背面</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-x-3 text-[9px] text-slate-500">
            <span><span style={{ color: "#34d399" }}>■</span> 回復済(やれる)</span>
            <span><span style={{ color: "#fbbf24" }}>■</span> 回復途中</span>
            <span><span style={{ color: "#f87171" }}>■</span> 直近に負荷</span>
            <span><span className="text-amber-300">▢</span> 今日のおすすめ</span>
          </div>
          {s.suggestion.length > 0 && (
            <p className="text-center text-[11px] text-slate-300">
              今日やるべき部位: <span className="font-semibold text-amber-300">{s.suggestion.map((x) => x.label).join(" / ")}</span>
            </p>
          )}
          <div className="grid gap-0.5">
            {orderedMuscle.map((m) => <MuscleRow key={m.key} m={m} />)}
          </div>
          <p className="text-[9px] text-slate-500">
            Garmin の活動から自動算出。背中(引く)は自重だと検出されにくく「伸びしろ」に出やすい。
            {s.muscle_confidence === "high" ? " 種目記録あり=精度高。" : " 活動種別から推定。"}
          </p>
        </>
      ) : (
        <>
          <div className="flex items-center justify-center gap-4 rounded-xl bg-slate-900/60 py-2">
            <BodyFigure fills={hpFig.fills} size={104} />
            <div className="text-center">
              <div className="text-[10px] text-slate-500">総合コンディション</div>
              <div className="text-2xl font-bold tabular-nums" style={{ color: hpColor(s.hp_total) }}>
                {s.hp_total ?? "—"}
              </div>
              <div className="text-[9px] text-slate-600">/ 100</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-x-3 text-[9px] text-slate-500">
            <span><span style={{ color: "#34d399" }}>■</span> 良好</span>
            <span><span style={{ color: "#fbbf24" }}>■</span> 注意</span>
            <span><span style={{ color: "#f87171" }}>■</span> 要対処</span>
          </div>
          <div className="grid gap-0.5">
            {s.hp.map((g) => <HpRow key={g.region} g={g} />)}
          </div>
          <p className="text-[9px] text-slate-500">
            各ゲージは実指標の裏付け: 頭=偏頭痛 / 胸=Body Battery / 腹=水分 / 腕・脚=筋の回復。"HP" は状態把握のためのメタファ。
          </p>
        </>
      )}
    </section>
  );
}

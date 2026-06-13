import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, ChevronDown, ChevronUp, Flame } from "lucide-react";
import { api } from "../lib/api";
import type { LearningCheckField, LearningChapter } from "../lib/api";

/**
 * The Rust Book 完走プラン (週1章・約5ヶ月) の進捗カード。
 *
 * 1 章のクリア条件は 3 点セット (読了 / Rustlings / 説明できた)。
 * 「説明できた」は Claude Code 相手の口頭試問に合格して初めてチェックする —
 * 読んだだけで分かったふりになるのを構造的に防ぐための設計。
 * チェックすると当日の学習ドメイン達成度 (ライフスコア) と翌朝の
 * LLM コーチングに反映される。
 */

const CHECKS: { key: LearningCheckField; label: string; hint: string }[] = [
  { key: "read", label: "読了", hint: "章を読み終えた" },
  { key: "rustlings", label: "Rustlings", hint: "該当セクションの演習を解いた" },
  { key: "explained", label: "説明できた", hint: "Claude の口頭試問に合格した" },
];

const PACE_LABEL: Record<string, { text: string; cls: string }> = {
  not_started: { text: "未開始", cls: "text-slate-500" },
  behind: { text: "遅れ気味 — でも続いてる", cls: "text-amber-400" },
  on_track: { text: "順調", cls: "text-emerald-400" },
  ahead: { text: "前倒し", cls: "text-sky-400" },
};

function ChapterRow({
  ch,
  isCurrent,
  onCheck,
  pending,
}: {
  ch: LearningChapter;
  isCurrent: boolean;
  onCheck: (chapter: number, field: LearningCheckField, done: boolean) => void;
  pending: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-2 rounded-lg px-2 py-1.5 ${
        isCurrent ? "bg-slate-800/80 ring-1 ring-emerald-500/40" : ""
      } ${ch.complete ? "opacity-50" : ""}`}
    >
      <span
        className={`w-9 shrink-0 text-[11px] tabular-nums ${
          ch.milestone ? "font-semibold text-amber-300" : "text-slate-400"
        }`}
      >
        ch{ch.chapter}
      </span>
      <span className="min-w-0 flex-1 truncate text-[12px] text-slate-200">
        {ch.title}
        {ch.milestone && <span className="ml-1 text-[10px] text-amber-400/80">⛰ 山場</span>}
      </span>
      <div className="flex shrink-0 gap-1">
        {CHECKS.map((c) => {
          const done = ch[c.key];
          return (
            <button
              key={c.key}
              type="button"
              disabled={pending}
              title={c.hint}
              onClick={() => onCheck(ch.chapter, c.key, !done)}
              className={`flex h-6 items-center gap-0.5 rounded-md border px-1.5 text-[10px] transition-colors ${
                done
                  ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-300"
                  : "border-slate-700 bg-slate-900/60 text-slate-500 hover:border-slate-500 hover:text-slate-300"
              }`}
            >
              {done && <Check size={10} />}
              {c.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PlanEditor({ s }: { s: import("../lib/api").LearningState }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (body: { started_on?: string; target_date?: string; clear_started?: boolean; clear_target?: boolean }) =>
      api.learningPlan(body),
    onSuccess: (st) => { qc.setQueryData(["learning"], st); },
  });
  const startVal = s.projection?.started_on ?? "";
  const targetVal = s.projection?.target_date ?? "";
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px]">
      <label className="flex items-center gap-1 text-slate-400">
        開始日
        <input type="date" value={startVal}
          onChange={(e) => save.mutate(e.target.value ? { started_on: e.target.value } : { clear_started: true })}
          className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-slate-200" />
      </label>
      <label className="flex items-center gap-1 text-slate-400">
        目標完了日
        <input type="date" value={targetVal}
          onChange={(e) => save.mutate(e.target.value ? { target_date: e.target.value } : { clear_target: true })}
          className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-slate-200" />
      </label>
    </div>
  );
}

function ProjectionGraph({ p }: { p: import("../lib/api").LearningProjection }) {
  const W = 320, H = 90, padL = 4, padR = 4, padT = 8, padB = 16;
  const start = new Date(p.series[0].date).getTime();
  const today = Date.now();
  const etaTs = p.eta_date ? new Date(p.eta_date).getTime() : today;
  const tMin = start - 12 * 3600_000;
  const y = (pct: number) => padT + (1 - pct / 100) * (H - padT - padB);
  const targetTs = p.target_date ? new Date(p.target_date).getTime() : null;
  const tMax2 = Math.max(etaTs, today, targetTs ?? 0) + 12 * 3600_000;
  const x2 = (ts: number) => padL + ((ts - tMin) / (tMax2 - tMin)) * (W - padL - padR);
  const confLabel = { none: "予測待ち", low: "精度 低", medium: "精度 中", high: "精度 高" }[p.confidence];
  const confColor = { none: "text-slate-600", low: "text-slate-500", medium: "text-sky-300", high: "text-emerald-300" }[p.confidence];
  const fmt = (iso: string | null) => (iso ? `${+iso.slice(5, 7)}/${+iso.slice(8, 10)}` : "--");
  return (
    <div className="rounded-xl bg-slate-900/60 p-2.5">
      <div className="mb-1 flex items-baseline justify-between text-[11px]">
        <span className="text-slate-300">完走予測</span>
        <span className={`text-[10px] ${confColor}`}>{confLabel}{p.done_units > 0 ? ` (n=${p.done_units})` : ""}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="完走予測グラフ">
        {[0, 50, 100].map((g) => (
          <line key={g} x1={padL} y1={y(g)} x2={W - padR} y2={y(g)} stroke="#1e293b" strokeWidth={0.5} />
        ))}
        {/* 目標完了日の縦線 */}
        {targetTs && (
          <>
            <line x1={x2(targetTs)} y1={padT} x2={x2(targetTs)} y2={H - padB} stroke={p.on_track === false ? "#fb7185" : "#a78bfa"} strokeWidth={0.8} strokeDasharray="2 2" opacity={0.7} />
            <text x={x2(targetTs)} y={padT + 6} fontSize={8} fill={p.on_track === false ? "#fb7185" : "#a78bfa"} textAnchor="middle">目標</text>
          </>
        )}
        <polyline points={p.series.map((s) => `${x2(new Date(s.date).getTime())},${y(s.pct)}`).join(" ")} fill="none" stroke="#34d399" strokeWidth={1.8} strokeLinejoin="round" />
        {p.eta_date && p.pct < 100 && (
          <line x1={x2(today)} y1={y(p.pct)} x2={x2(etaTs)} y2={y(100)} stroke="#38bdf8" strokeWidth={1.5} strokeDasharray="3 3" />
        )}
        <circle cx={x2(today)} cy={y(p.pct)} r={2.5} fill="#34d399" />
        {p.eta_date && p.pct < 100 && <circle cx={x2(etaTs)} cy={y(100)} r={2.5} fill="#38bdf8" />}
        <text x={x2(start)} y={H - 4} fontSize={9} fill="#64748b" textAnchor="start">{fmt(p.series[0].date)} 開始</text>
        {p.eta_date && p.pct < 100 && (
          <text x={W - padR} y={H - 4} fontSize={9} fill="#38bdf8" textAnchor="end">{fmt(p.eta_date)} 完走予測</text>
        )}
      </svg>
      <p className="mt-0.5 text-[10px] text-slate-400">
        {fmt(p.started_on)}開始 · {p.pct}%完了 ({p.done_units}/{p.total_units}項目){p.done_units > 0 ? ` · 週${p.pace_per_week}項目ペース` : ""}
        {p.eta_date && p.pct < 100 ? ` → このペースで ${fmt(p.eta_date)}頃 完走` : p.pct >= 100 ? " → 完走!" : p.done_units === 0 ? " → チェックを入れると予測開始" : ""}
        {p.target_date && p.on_track != null ? (p.on_track ? " ✓目標内" : " ⚠目標に遅れ") : ""}
      </p>
    </div>
  );
}

export function LearningCard() {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const q = useQuery({ queryKey: ["learning"], queryFn: api.learningState });
  const check = useMutation({
    mutationFn: ({ chapter, field, done }: { chapter: number; field: LearningCheckField; done: boolean }) =>
      api.learningCheck(chapter, field, done),
    onSuccess: (state) => {
      qc.setQueryData(["learning"], state);
      // 学習ドメインの achievement が変わるのでライフスコアも更新
      qc.invalidateQueries({ queryKey: ["life"] });
    },
  });

  if (q.isLoading || !q.data) {
    return (
      <section className="space-y-2 rounded-2xl bg-slate-900/40 p-4">
        <span className="text-xs text-slate-500">学習プランを読み込み中…</span>
      </section>
    );
  }

  const s = q.data;
  const current = s.chapters.find((c) => c.chapter === s.current_chapter) ?? null;
  const pace = PACE_LABEL[s.pace] ?? PACE_LABEL.not_started;
  const pct = Math.round((s.done_count / s.total) * 100);
  // 折りたたみ時は現在章の前後だけ表示して圧迫しない
  const visible = expanded
    ? s.chapters
    : s.chapters.filter(
        (c) => s.current_chapter != null && Math.abs(c.chapter - s.current_chapter) <= 1,
      );

  const onCheck = (chapter: number, field: LearningCheckField, done: boolean) =>
    check.mutate({ chapter, field, done });

  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center gap-1.5">
        <BookOpen size={14} className="text-amber-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">
          The Book 完走プラン
        </span>
        <span className={`text-[10px] ${pace.cls}`}>{pace.text}</span>
        <span className="ml-auto flex items-center gap-2">
          {s.streak_sessions > 0 && (
            <span className="flex items-center gap-0.5 text-[11px] text-orange-400">
              <Flame size={11} />
              {s.streak_sessions}回継続
            </span>
          )}
          <span className="text-[11px] tabular-nums text-slate-400">
            {s.done_count}/{s.total} 章
          </span>
        </span>
      </div>

      {/* 進捗バー */}
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-amber-500 to-emerald-500 transition-all"
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>

      {/* 開始日・目標完了日の記録 + 完走予測グラフ */}
      <PlanEditor s={s} />
      {s.projection && <ProjectionGraph p={s.projection} />}

      {s.completed ? (
        <p className="text-sm font-semibold text-emerald-300">
          🎉 完走！The Rust Book 全 {s.total} 章クリア。次は卒業制作へ。
        </p>
      ) : current ? (
        <>
          <div className="text-[12px] text-slate-300">
            今週の章: <span className="font-semibold text-slate-100">ch{current.chapter} {current.title}</span>
            {current.note && (
              <p className="mt-0.5 text-[11px] text-amber-400/90">{current.note}</p>
            )}
          </div>
          <div className="grid gap-1">
            {visible.map((ch) => (
              <ChapterRow
                key={ch.chapter}
                ch={ch}
                isCurrent={ch.chapter === s.current_chapter}
                onCheck={onCheck}
                pending={check.isPending}
              />
            ))}
          </div>
        </>
      ) : null}

      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">
          「説明できた」は Claude の口頭試問に合格してから
        </span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-0.5 text-[10px] text-slate-500 hover:text-slate-300"
        >
          {expanded ? (
            <>
              <ChevronUp size={11} /> 折りたたむ
            </>
          ) : (
            <>
              <ChevronDown size={11} /> 全{s.total}章を表示
            </>
          )}
        </button>
      </div>
    </section>
  );
}

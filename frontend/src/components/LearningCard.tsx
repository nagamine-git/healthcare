import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, ChevronDown, ChevronUp, Flame, GraduationCap } from "lucide-react";
import { api } from "../lib/api";
import type { LearningCheckField, LearningChapter } from "../lib/api";
import { ChapterQuiz } from "./ChapterQuiz";
import { P } from "../lib/palette";

/**
 * The Rust Book 完走プラン (週1章・約5ヶ月) の進捗カード。
 *
 * 1 章のクリア条件は 3 点セット (読了 / Rustlings / 説明できた)。
 * 「説明できた」は Claude Code 相手の口頭試問に合格して初めてチェックする —
 * 読んだだけで分かったふりになるのを構造的に防ぐための設計。
 * チェックすると当日の学習ドメイン達成度 (ライフスコア) と翌朝の
 * LLM コーチングに反映される。
 */

// 節 (最下層) は 読了 / 説明 の 2 点。Rustlings は演習が章 (トピック) 単位のため章で扱う。
const CHECKS: { key: LearningCheckField; label: string; hint: string }[] = [
  { key: "read", label: "読了", hint: "節を読み終えた" },
  { key: "explained", label: "説明できた", hint: "Claude の口頭試問に合格した" },
];

const PACE_LABEL: Record<string, { text: string; cls: string }> = {
  not_started: { text: "未開始", cls: "text-ink-faint" },
  behind: { text: "遅れ気味 — でも続いてる", cls: "text-act-300" },
  on_track: { text: "順調", cls: "text-prog-300" },
  ahead: { text: "前倒し", cls: "text-sky-400" },
};

function SectionRow({
  s,
  onCheck,
  pending,
}: {
  s: import("../lib/api").LearningSection;
  onCheck: (sectionId: string, field: LearningCheckField, done: boolean) => void;
  pending: boolean;
}) {
  return (
    <div className={`rounded-md px-1.5 py-1.5 ${s.done ? "opacity-60" : ""}`}>
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="w-8 shrink-0 tabular-nums text-ink-faint">{s.id}</span>
        <span className={`min-w-0 flex-1 ${s.done ? "text-ink-dim line-through" : "text-ink-dim"}`}>{s.title}</span>
      </div>
      {/* 最下層の 2 点チェック (読了 / 説明できた)。モバイルでも折り返す */}
      <div className="mt-1 flex flex-wrap gap-1 pl-10">
        {CHECKS.map((c) => {
          const done = s[c.key];
          return (
            <button key={c.key} type="button" disabled={pending} title={c.hint}
              onClick={() => onCheck(s.id, c.key, !done)}
              className={`flex h-6 items-center gap-0.5 rounded-md border px-1.5 text-[10px] transition-colors ${
                done ? "border-prog-500/60 bg-prog-500/20 text-prog-300"
                     : "border-hairline bg-hull/60 text-ink-faint hover:border-panel hover:text-ink-dim"}`}>
              {done && <Check size={10} className="shrink-0" />}
              {c.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ChapterRow({
  ch,
  isCurrent,
  onCheck,
  onRustlings,
  onQuiz,
  pending,
}: {
  ch: LearningChapter;
  isCurrent: boolean;
  onCheck: (sectionId: string, field: LearningCheckField, done: boolean) => void;
  onRustlings: (chapter: number, done: boolean) => void;
  onQuiz: (ch: LearningChapter) => void;
  pending: boolean;
}) {
  const [open, setOpen] = useState(isCurrent);
  // 今日のノルマ帯で左ボーダーを色分け: 楽観(最低)=sky / 悲観(安全)=amber / その先=灰
  const BAND_BORDER: Record<string, string> = {
    min: "border-l-2 border-sky-400/70",
    safe: "border-l-2 border-act-700/70",
    later: "border-l-2 border-hairline/60",
    done: "border-l-2 border-prog-500/50",
  };
  const bandCls = ch.band ? BAND_BORDER[ch.band] ?? "" : "";
  return (
    <div className={`rounded-lg ${bandCls} ${isCurrent ? "bg-panel/80 ring-1 ring-prog-500/40" : ""} ${ch.complete ? "opacity-60" : ""}`}>
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="flex w-full min-w-0 items-center gap-2 px-2 py-1.5 text-left">
        {open ? <ChevronUp size={12} className="shrink-0 text-ink-faint" /> : <ChevronDown size={12} className="shrink-0 text-ink-faint" />}
        <span className={`w-9 shrink-0 text-[11px] tabular-nums ${ch.milestone ? "font-semibold text-act-300" : "text-ink-dim"}`}>ch{ch.chapter}</span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-ink">
          {ch.title}
          {ch.milestone && <span className="ml-1 text-[10px] text-act-300/80">⛰ 山場</span>}
        </span>
        {ch.complete && <Check size={12} className="shrink-0 text-prog-300" />}
        <span className={`shrink-0 text-[10px] tabular-nums ${ch.section_done === ch.section_total ? "text-prog-300" : "text-ink-faint"}`}>
          {ch.section_done}/{ch.section_total}節
        </span>
      </button>
      {open && (
        <div className="px-1 pb-2 pl-3">
          {/* 節 (subsection) ごとの 2 点チェック */}
          <div className="grid gap-0.5">
            {ch.sections.map((s) => (
              <SectionRow key={s.id} s={s} onCheck={onCheck} pending={pending} />
            ))}
          </div>
          {/* Rustlings (章単位)。演習のある章だけ表示 */}
          {ch.has_rustlings && (
            <div className="mt-1.5 flex items-center gap-2 pl-1.5">
              <button type="button" disabled={pending}
                title={`rustlings ${ch.rustlings_topic ?? ""} を解いた`}
                onClick={() => onRustlings(ch.chapter, !ch.rustlings)}
                className={`flex h-6 items-center gap-0.5 rounded-md border px-1.5 text-[10px] transition-colors ${
                  ch.rustlings ? "border-prog-500/60 bg-prog-500/20 text-prog-300"
                               : "border-hairline bg-hull/60 text-ink-faint hover:border-panel hover:text-ink-dim"}`}>
                {ch.rustlings && <Check size={10} className="shrink-0" />}
                Rustlings
              </button>
              <span className="min-w-0 flex-1 truncate text-[9px] text-ink-faint">{ch.rustlings_topic}</span>
            </div>
          )}
          {/* 口頭試問 — 「説明できた」をClaudeが判定して付与 */}
          <button type="button" onClick={() => onQuiz(ch)}
            className={`mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border py-2 text-[11px] transition-colors ${
              ch.explained
                ? "border-prog-500/40 bg-prog-500/10 text-prog-300"
                : "border-act-700/40 bg-act/10 text-act-300 hover:bg-act/20"}`}>
            <GraduationCap size={13} />
            {ch.explained ? "理解度クリア済み — もう一度挑戦" : "理解度テストで「説明できた」を判定"}
          </button>
        </div>
      )}
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
      <label className="flex items-center gap-1 text-ink-dim">
        開始日
        <input type="date" value={startVal}
          onChange={(e) => save.mutate(e.target.value ? { started_on: e.target.value } : { clear_started: true })}
          className="rounded border border-hairline bg-panel px-1.5 py-0.5 text-ink" />
      </label>
      <label className="flex items-center gap-1 text-ink-dim">
        目標完了日
        <input type="date" value={targetVal}
          onChange={(e) => save.mutate(e.target.value ? { target_date: e.target.value } : { clear_target: true })}
          className="rounded border border-hairline bg-panel px-1.5 py-0.5 text-ink" />
      </label>
    </div>
  );
}

const GOAL_LABEL: Record<string, { text: string; cls: string }> = {
  safe: { text: "✓ 達成ほぼ確実", cls: "text-prog-300" },
  likely: { text: "達成見込み", cls: "text-sky-300" },
  at_risk: { text: "⚠ ギリギリ", cls: "text-act-300" },
  unlikely: { text: "⚠ 目標に届かない見込み", cls: "text-risk" },
};

function ProjectionGraph({ p }: { p: import("../lib/api").LearningProjection }) {
  const W = 320, H = 96, padL = 4, padR = 4, padT = 8, padB = 16;
  const start = new Date(p.series[0].date).getTime();
  const today = Date.now();
  const ts = (iso: string | null) => (iso ? new Date(iso).getTime() : today);
  const etaN = ts(p.eta_normal);
  const etaBest = ts(p.eta_best);
  const etaWorst = ts(p.eta_worst);
  const targetTs = p.target_date ? new Date(p.target_date).getTime() : null;
  const tMin = start - 12 * 3600_000;
  const tMax = Math.max(etaN, etaBest, etaWorst, today, targetTs ?? 0) + 12 * 3600_000;
  const x = (t: number) => padL + ((t - tMin) / (tMax - tMin)) * (W - padL - padR);
  const y = (pct: number) => padT + (1 - pct / 100) * (H - padT - padB);
  const confLabel = { none: "予測待ち", low: "精度 低", medium: "精度 中", high: "精度 高" }[p.confidence];
  const confColor = { none: "text-ink-faint", low: "text-ink-faint", medium: "text-sky-300", high: "text-prog-300" }[p.confidence];
  const fmt = (iso: string | null) => (iso ? `${+iso.slice(5, 7)}/${+iso.slice(8, 10)}` : "--");
  const showProj = p.pct < 100 && p.done_units > 0;
  const goal = p.goal_status ? GOAL_LABEL[p.goal_status] : null;
  // best/worst を結ぶ予測帯 (today,pct → 100%) の塗り
  const band = showProj
    ? `${x(today)},${y(p.pct)} ${x(etaBest)},${y(100)} ${x(etaWorst)},${y(100)}`
    : "";
  return (
    <div className="rounded-xl bg-hull/60 p-2.5">
      <div className="mb-1 flex items-baseline justify-between gap-2 text-[11px]">
        <span className="text-ink-dim">完走予測</span>
        <span className="ml-auto flex items-baseline gap-2">
          {goal && <span className={`text-[10px] ${goal.cls}`}>{goal.text}</span>}
          <span className={`text-[10px] ${confColor}`}>{confLabel}{p.done_units > 0 ? ` (n=${p.done_units})` : ""}</span>
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="完走予測グラフ">
        {[0, 50, 100].map((g) => (
          <line key={g} x1={padL} y1={y(g)} x2={W - padR} y2={y(g)} stroke={P.panel} strokeWidth={0.5} />
        ))}
        {/* 予測帯 (好調〜不調の幅) */}
        {showProj && <polygon points={band} fill={P.act300} opacity={0.1} />}
        {/* 目標線 (開始0%→目標日100%、グレー直線) */}
        {targetTs && (
          <line x1={x(start)} y1={y(0)} x2={x(targetTs)} y2={y(100)} stroke={P.inkFaint} strokeWidth={1.3} />
        )}
        {/* best予想 (好調 1.43倍速) / N予想 (標準) / worst予想 (不調 0.7倍) */}
        {showProj && p.eta_best && (
          <line x1={x(today)} y1={y(p.pct)} x2={x(etaBest)} y2={y(100)} stroke={P.act300} strokeWidth={1.1} strokeDasharray="2 2" opacity={0.7} />
        )}
        {showProj && p.eta_worst && (
          <line x1={x(today)} y1={y(p.pct)} x2={x(etaWorst)} y2={y(100)} stroke={P.act300} strokeWidth={1.1} strokeDasharray="2 2" opacity={0.7} />
        )}
        {showProj && p.eta_normal && (
          <line x1={x(today)} y1={y(p.pct)} x2={x(etaN)} y2={y(100)} stroke={P.act300} strokeWidth={1.5} strokeDasharray="5 3" opacity={0.9} />
        )}
        {/* 実測 (オレンジ実線) */}
        <polyline points={p.series.map((s) => `${x(new Date(s.date).getTime())},${y(s.pct)}`).join(" ")} fill="none" stroke={P.act} strokeWidth={1.8} strokeLinejoin="round" />
        <circle cx={x(today)} cy={y(p.pct)} r={2.5} fill={P.act} />
        <text x={x(start)} y={H - 4} fontSize={9} fill={P.inkFaint} textAnchor="start">{fmt(p.series[0].date)}開始</text>
        {showProj && <text x={W - padR} y={H - 4} fontSize={9} fill={P.act300} textAnchor="end">完走 {fmt(p.eta_best)}〜{fmt(p.eta_worst)}</text>}
      </svg>
      {/* 凡例 */}
      <div className="mt-0.5 flex flex-wrap gap-x-3 text-[9px] text-ink-faint">
        <span><span className="text-act-300">━</span> 実測</span>
        <span><span className="text-act-300">╌</span> 標準ペース</span>
        <span><span className="text-act-300/70">┈</span> 好調〜不調(±0.7×)</span>
        {targetTs && <span><span className="text-ink-dim">━</span> 目標</span>}
      </div>
      <p className="mt-0.5 text-[10px] text-ink-dim">
        {fmt(p.started_on)}開始 · {p.pct}%完了 ({p.done_units}/{p.total_units}チェック){p.done_units > 0 ? ` · 平均週${p.pace_per_week}チェック` : ""}
        {showProj ? ` → 標準${fmt(p.eta_normal)}頃 (好調${fmt(p.eta_best)}〜不調${fmt(p.eta_worst)})` : p.pct >= 100 ? " → 完走!" : p.done_units === 0 ? " → チェックすると予測開始" : ""}
      </p>
      {/* 今日のノルマ 2 段階: 楽観ライン(最低) と 悲観ライン(安全)。両方オンスケ */}
      {p.target_date && p.target_today_min && p.target_today_safe && (
        <div className="mt-1.5 space-y-1 rounded-lg bg-hull/60 px-2.5 py-1.5">
          <div className="text-[10px] text-ink-dim">今日のノルマ (目標{fmt(p.target_date)}まで{p.days_left}日)</div>
          <div className="flex items-baseline gap-1.5 text-[11px]">
            <span className="shrink-0 rounded bg-sky-500/20 px-1 text-[9px] text-sky-300">楽観 最低</span>
            <span className="min-w-0 flex-1 truncate text-sky-100">{p.target_today_min.label}</span>
          </div>
          <div className="flex items-baseline gap-1.5 text-[11px]">
            <span className="shrink-0 rounded bg-act/20 px-1 text-[9px] text-act-300">悲観 安全</span>
            <span className="min-w-0 flex-1 truncate text-act-300">{p.target_today_safe.label}</span>
          </div>
          <div className="text-[9px] text-ink-faint">
            楽観なら好調維持で間に合う最低ライン / 悲観なら不調でも間に合う安全ライン
          </div>
        </div>
      )}
    </div>
  );
}

export function LearningCard() {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [quizCh, setQuizCh] = useState<LearningChapter | null>(null);
  const q = useQuery({ queryKey: ["learning"], queryFn: api.learningState });
  const section = useMutation({
    mutationFn: ({ id, field, done }: { id: string; field: LearningCheckField; done: boolean }) =>
      api.learningSection(id, field, done),
    onSuccess: (state) => {
      qc.setQueryData(["learning"], state);
      qc.invalidateQueries({ queryKey: ["life"] });
    },
  });
  const rustlings = useMutation({
    mutationFn: ({ chapter, done }: { chapter: number; done: boolean }) =>
      api.learningRustlings(chapter, done),
    onSuccess: (state) => {
      qc.setQueryData(["learning"], state);
      qc.invalidateQueries({ queryKey: ["life"] });
    },
  });

  if (q.isLoading || !q.data) {
    return (
      <section className="space-y-2 rounded-2xl bg-hull/40 p-4">
        <span className="text-xs text-ink-faint">学習プランを読み込み中…</span>
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

  const onCheck = (id: string, field: LearningCheckField, done: boolean) =>
    section.mutate({ id, field, done });
  const onRustlings = (chapter: number, done: boolean) => rustlings.mutate({ chapter, done });

  return (
    <section className="space-y-3 rounded-2xl bg-hull/40 p-4">
      <div className="flex items-center gap-1.5">
        <BookOpen size={14} className="text-act-300" />
        <span className="text-xs uppercase tracking-wider text-ink-dim">
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
          <span className="text-[11px] tabular-nums text-ink-dim">
            {s.done_count}/{s.total} 章
          </span>
        </span>
      </div>

      {/* 進捗バー */}
      <div className="h-1.5 overflow-hidden rounded-full bg-panel">
        <div
          className="h-full rounded-full bg-gradient-to-r from-act to-prog-500 transition-all"
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>

      {/* 開始日・目標完了日の記録 + 完走予測グラフ */}
      <PlanEditor s={s} />
      {s.projection && <ProjectionGraph p={s.projection} />}

      {s.completed ? (
        <p className="text-sm font-semibold text-prog-300">
          🎉 完走！The Rust Book 全 {s.total} 章クリア。次は卒業制作へ。
        </p>
      ) : current ? (
        <>
          <div className="text-[12px] text-ink-dim">
            今週の章: <span className="font-semibold text-ink">ch{current.chapter} {current.title}</span>
            {current.note && (
              <p className="mt-0.5 text-[11px] text-act-300/90">{current.note}</p>
            )}
          </div>
          {/* 章一覧の左ボーダー色 = 今日のノルマ帯 */}
          {s.projection?.target_today_safe && (
            <div className="flex flex-wrap gap-x-3 text-[9px] text-ink-faint">
              <span><span className="text-sky-400">▌</span>楽観ノルマ(最低)</span>
              <span><span className="text-act-300">▌</span>悲観ノルマ(安全)</span>
              <span><span className="text-ink-faint">▌</span>その先</span>
            </div>
          )}
          <div className="grid gap-1">
            {visible.map((ch) => (
              <ChapterRow
                key={ch.chapter}
                ch={ch}
                isCurrent={ch.chapter === s.current_chapter}
                onCheck={onCheck}
                onRustlings={onRustlings}
                onQuiz={setQuizCh}
                pending={section.isPending || rustlings.isPending}
              />
            ))}
          </div>
        </>
      ) : null}

      <div className="flex items-center justify-between">
        <span className="text-[10px] text-ink-faint">
          「説明できた」は Claude の口頭試問に合格してから
        </span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-0.5 text-[10px] text-ink-faint hover:text-ink-dim"
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

      {quizCh && <ChapterQuiz ch={quizCh} onClose={() => setQuizCh(null)} />}
    </section>
  );
}

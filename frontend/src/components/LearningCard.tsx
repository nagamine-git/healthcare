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

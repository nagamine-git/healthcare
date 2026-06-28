import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Send, GraduationCap, Check, ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import type { LearningChapter, QuizFormat } from "../lib/api";
import { ChatMarkdown } from "./ChatMarkdown";

/**
 * 章の理解度テスト (得点制) チャットモーダル。
 *
 * 問題ごとに回答形式を選べる: 記述 (フリーワード, +50) / 4択 (+20) / 2択 (+10)。
 * 難しい形式ほど高得点。累計が 100 点に達し、かつ記述で 1 回以上正解 (理解度80%+) すると
 * 章クリア → 全節 explained が立つ。易しい選択式だけでは品質フロアにより逃げ切れない。
 * クリア後は採点をやめ、復習チューターに切り替わる。
 */

type Msg = { role: "user" | "assistant"; content: string };
type ChoiceQ = { question: string; options: string[]; correctIndex: number; explanation: string };
type Answered = { selected: number; correct: boolean; explanation: string };

const FORMATS: { key: QuizFormat; label: string; pts: string }[] = [
  { key: "free", label: "記述", pts: "+50" },
  { key: "choice4", label: "4択", pts: "+20" },
  { key: "choice2", label: "2択", pts: "+10" },
];

export function ChapterQuiz({ ch, onClose }: { ch: LearningChapter; onClose: () => void }) {
  const qc = useQueryClient();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [format, setFormat] = useState<QuizFormat>("free");
  const [points, setPoints] = useState(ch.quiz_points ?? 0);
  const [target, setTarget] = useState(ch.quiz_target ?? 100);
  const [freeWordPassed, setFreeWordPassed] = useState(ch.free_word_passed ?? false);
  const [understanding, setUnderstanding] = useState(0);
  const [cleared, setCleared] = useState(false);
  const [choiceQ, setChoiceQ] = useState<ChoiceQ | null>(null);
  const [answered, setAnswered] = useState<Answered | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const applyProgress = (r: {
    quiz_points?: number;
    target?: number;
    free_word_passed?: boolean;
    cleared?: boolean;
    state?: unknown;
  }) => {
    if (typeof r.quiz_points === "number") setPoints(r.quiz_points);
    if (typeof r.target === "number") setTarget(r.target);
    if (typeof r.free_word_passed === "boolean") setFreeWordPassed(r.free_word_passed);
    if (r.cleared) {
      setCleared(true);
      if (r.state) qc.setQueryData(["learning"], r.state);
      qc.invalidateQueries({ queryKey: ["life"] });
    }
  };

  // 記述 (フリーワード) の 1 ターン
  const free = useMutation({
    mutationFn: ({ history, mode }: { history: Msg[]; mode: "exam" | "review" }) =>
      api.learningQuiz(ch.chapter, history, { mode, format: "free" }),
    onSuccess: (r, vars) => {
      if (r.reply) setMsgs((m) => [...m, { role: "assistant", content: r.reply as string }]);
      if (vars.mode === "exam") {
        if (typeof r.understanding === "number") setUnderstanding(r.understanding);
        applyProgress(r);
      }
    },
  });

  // 選択式の問題生成
  const genChoice = useMutation({
    mutationFn: (fmt: "choice4" | "choice2") =>
      api.learningQuiz(ch.chapter, msgs, { format: fmt, action: "question" }),
    onSuccess: (r) => {
      if (!r.question || !r.options) return;
      setChoiceQ({
        question: r.question,
        options: r.options,
        correctIndex: r.correct_index ?? 0,
        explanation: r.explanation ?? "",
      });
      setAnswered(null);
      applyProgress(r);
    },
  });

  // 選択式の採点
  const ansChoice = useMutation({
    mutationFn: ({ fmt, selected, correctIndex }: { fmt: "choice4" | "choice2"; selected: number; correctIndex: number }) =>
      api.learningQuiz(ch.chapter, msgs, {
        format: fmt,
        action: "answer",
        selected_index: selected,
        correct_index: correctIndex,
      }),
    onSuccess: (r, vars) => {
      const correct = Boolean(r.correct);
      const q = choiceQ;
      setAnswered({ selected: vars.selected, correct, explanation: q?.explanation ?? "" });
      // 履歴に記録 (次の生成で重複を避けるため)
      if (q) {
        const label = vars.fmt === "choice4" ? "4択" : "2択";
        setMsgs((m) => [
          ...m,
          { role: "assistant", content: `【${label}】${q.question}` },
          { role: "user", content: `選択: ${q.options[vars.selected]}（${correct ? "正解" : "不正解"}）` },
        ]);
      }
      applyProgress(r);
    },
  });

  const busy = free.isPending || genChoice.isPending || ansChoice.isPending;

  // 開いたら記述の最初の質問から開始
  useEffect(() => {
    free.mutate({ history: [], mode: "exam" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs, busy, choiceQ, answered]);

  const pct = target > 0 ? Math.min(100, (points / target) * 100) : 0;
  const barColor = cleared ? "#34d399" : "#fbbf24";

  const sendFree = () => {
    const text = input.trim();
    if (!text || busy) return;
    const next = [...msgs, { role: "user" as const, content: text }];
    setMsgs(next);
    setInput("");
    free.mutate({ history: next, mode: cleared ? "review" : "exam" });
  };

  const pickFormat = (fmt: QuizFormat) => {
    if (busy || cleared) return;
    setFormat(fmt);
    setChoiceQ(null);
    setAnswered(null);
    if (fmt !== "free") genChoice.mutate(fmt);
  };

  const answer = (idx: number) => {
    if (busy || !choiceQ || answered || format === "free") return;
    ansChoice.mutate({ fmt: format as "choice4" | "choice2", selected: idx, correctIndex: choiceQ.correctIndex });
  };

  const nextChoice = () => {
    if (busy || format === "free") return;
    genChoice.mutate(format as "choice4" | "choice2");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center" onClick={onClose}>
      <div
        className="flex h-[85vh] w-full max-w-lg flex-col rounded-t-2xl bg-hull sm:h-[80vh] sm:rounded-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ヘッダ + 得点バー */}
        <div className="border-b border-panel px-4 py-3">
          <div className="flex items-center gap-2">
            <GraduationCap size={16} className="text-act-300" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-ink">ch{ch.chapter} {ch.title} 理解度テスト</div>
              <div className="text-[10px] text-ink-faint">
                得点{target}でクリア・記述で1回以上正解が必須{understanding > 0 ? ` ・直近理解度${understanding}%` : ""}
              </div>
            </div>
            <button type="button" onClick={onClose} className="rounded-lg p-1 text-ink-dim hover:bg-panel">
              <X size={18} />
            </button>
          </div>
          {/* 得点進捗バー */}
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[10px] text-ink-dim">得点</span>
            <div className="relative h-2.5 flex-1 overflow-hidden rounded-full bg-panel">
              <div className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: barColor }} />
            </div>
            <span className="shrink-0 text-right text-[12px] font-semibold tabular-nums" style={{ color: barColor }}>
              {points}/{target}
            </span>
          </div>
          {!freeWordPassed && !cleared && (
            <div className="mt-1 text-[10px] text-act-300/80">記述で1回正解するとクリア解禁(品質フロア)</div>
          )}
        </div>

        {/* 会話 */}
        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {msgs.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[85%] rounded-xl px-3 py-2 text-[13px] leading-relaxed ${
                  m.role === "user"
                    ? "whitespace-pre-wrap bg-act/20 text-act-300"
                    : "bg-panel text-ink"
                }`}
              >
                {m.role === "user" ? m.content : <ChatMarkdown content={m.content} />}
              </div>
            </div>
          ))}

          {/* 選択式の出題カード */}
          {format !== "free" && choiceQ && (
            <div className="rounded-xl border border-hairline bg-panel/60 p-3">
              <div className="mb-2 text-[13px] font-medium text-ink">{choiceQ.question}</div>
              <div className="space-y-1.5">
                {choiceQ.options.map((opt, i) => {
                  const isCorrect = i === choiceQ.correctIndex;
                  const picked = answered?.selected === i;
                  let cls = "border-hairline bg-panel text-ink hover:border-act/50";
                  if (answered) {
                    if (isCorrect) cls = "border-prog/60 bg-prog-500/15 text-prog-300";
                    else if (picked) cls = "border-risk/60 bg-risk/15 text-risk";
                    else cls = "border-panel bg-panel/40 text-ink-faint";
                  }
                  return (
                    <button
                      key={i}
                      type="button"
                      disabled={busy || Boolean(answered)}
                      onClick={() => answer(i)}
                      className={`flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-[13px] transition ${cls}`}
                    >
                      <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-current text-[11px]">
                        {String.fromCharCode(65 + i)}
                      </span>
                      <span className="flex-1">{opt}</span>
                      {answered && isCorrect && <Check size={15} className="shrink-0" />}
                      {answered && picked && !isCorrect && <X size={15} className="shrink-0" />}
                    </button>
                  );
                })}
              </div>
              {answered && (
                <div className="mt-2 space-y-2">
                  <div className={`text-[12px] font-medium ${answered.correct ? "text-prog-300" : "text-risk"}`}>
                    {answered.correct ? "正解！" : "不正解"}
                  </div>
                  {answered.explanation && (
                    <div className="text-[12px] leading-relaxed text-ink-dim">{answered.explanation}</div>
                  )}
                  {!cleared && (
                    <button
                      type="button"
                      onClick={nextChoice}
                      disabled={busy}
                      className="inline-flex items-center gap-1 rounded-lg bg-act/80 px-3 py-1.5 text-[12px] font-medium text-hull hover:bg-act disabled:opacity-50"
                    >
                      次の問題 <ChevronRight size={14} />
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {busy && (
            <div className="flex justify-start">
              <div className="rounded-xl bg-panel px-3 py-2 text-[13px] text-ink-faint">…</div>
            </div>
          )}
          {cleared && (
            <div className="flex items-start gap-1.5 rounded-xl bg-prog-500/15 px-3 py-2 text-[13px] text-prog-300">
              <Check size={16} className="mt-0.5 shrink-0" />
              <span>
                クリア！{points}点到達 —「説明できた」を付与しました。
                ここからは<span className="font-semibold">復習モード</span>。苦手だった所を質問すると、わかりやすく解説します。
              </span>
            </div>
          )}
        </div>

        {/* 形式選択 (クリア前のみ) */}
        {!cleared && (
          <div className="flex items-center gap-1.5 border-t border-panel px-3 pt-2">
            <span className="text-[10px] text-ink-faint">形式</span>
            {FORMATS.map((f) => (
              <button
                key={f.key}
                type="button"
                disabled={busy}
                onClick={() => pickFormat(f.key)}
                className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition disabled:opacity-50 ${
                  format === f.key
                    ? "bg-act text-hull"
                    : "bg-panel text-ink-dim hover:bg-hairline"
                }`}
              >
                {f.label}<span className="ml-1 opacity-60">{f.pts}</span>
              </button>
            ))}
          </div>
        )}

        {/* 入力 — 記述 or 復習チャット時のみ。選択式は上のカードで回答 */}
        {(format === "free" || cleared) && (
          <div className="border-t border-panel p-3">
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendFree(); }
                }}
                rows={2}
                placeholder={cleared ? "苦手な所を質問… (⌘+Enterで送信)" : "自分の言葉で説明… (⌘+Enterで送信)"}
                disabled={busy}
                className={`max-h-32 min-h-[44px] flex-1 resize-none rounded-xl border border-hairline bg-panel px-3 py-2 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none ${
                  cleared ? "focus:border-prog/60" : "focus:border-act/60"
                }`}
              />
              <button type="button" onClick={sendFree} disabled={busy || !input.trim()}
                className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl text-hull disabled:opacity-40 ${
                  cleared ? "bg-prog-500" : "bg-act"
                }`}>
                <Send size={18} />
              </button>
            </div>
          </div>
        )}

        {/* 選択式で未出題のとき (= 形式切替直後に生成失敗等) のフォールバック */}
        {format !== "free" && !cleared && !choiceQ && !busy && (
          <div className="border-t border-panel p-3">
            <button
              type="button"
              onClick={nextChoice}
              className="w-full rounded-xl bg-act/80 py-2 text-[13px] font-medium text-hull hover:bg-act"
            >
              問題を出す
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

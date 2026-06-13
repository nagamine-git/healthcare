import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Send, GraduationCap, Check } from "lucide-react";
import { api } from "../lib/api";
import type { LearningChapter } from "../lib/api";

/**
 * 章の口頭試問 (Socratic oral exam) チャットモーダル。
 *
 * 試験官 Claude がその章の核心を「自分の言葉で説明させる」 — retrieval practice。
 * 合格判定が出たら章の全節 explained が立ち、学習カードに即反映する。
 * 会話履歴はこのコンポーネントが保持する単発セッション。
 */

type Msg = { role: "user" | "assistant"; content: string };

export function ChapterQuiz({ ch, onClose }: { ch: LearningChapter; onClose: () => void }) {
  const qc = useQueryClient();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [passed, setPassed] = useState<boolean | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const turn = useMutation({
    mutationFn: (history: Msg[]) => api.learningQuiz(ch.chapter, history),
    onSuccess: (r) => {
      setMsgs((m) => [...m, { role: "assistant", content: r.reply }]);
      if (r.verdict.decided) {
        setPassed(r.verdict.passed);
        if (r.verdict.passed && r.state) qc.setQueryData(["learning"], r.state);
        if (r.verdict.passed) qc.invalidateQueries({ queryKey: ["life"] });
      }
    },
  });

  // 開いたら試験官が最初の質問から開始
  useEffect(() => {
    turn.mutate([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs, turn.isPending]);

  const send = () => {
    const text = input.trim();
    if (!text || turn.isPending || passed) return;
    const next = [...msgs, { role: "user" as const, content: text }];
    setMsgs(next);
    setInput("");
    turn.mutate(next);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center" onClick={onClose}>
      <div
        className="flex h-[85vh] w-full max-w-lg flex-col rounded-t-2xl bg-slate-900 sm:h-[80vh] sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ヘッダ */}
        <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
          <GraduationCap size={16} className="text-amber-300" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-slate-100">ch{ch.chapter} {ch.title} 口頭試問</div>
            <div className="text-[10px] text-slate-500">自分の言葉で説明 — 合格でClaudeが「説明できた」を付与</div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-800">
            <X size={18} />
          </button>
        </div>

        {/* 会話 */}
        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {msgs.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-[13px] leading-relaxed ${
                  m.role === "user"
                    ? "bg-amber-500/20 text-amber-50"
                    : "bg-slate-800 text-slate-200"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
          {turn.isPending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-slate-800 px-3 py-2 text-[13px] text-slate-500">…</div>
            </div>
          )}
          {passed === true && (
            <div className="flex items-center justify-center gap-1.5 rounded-xl bg-emerald-500/15 px-3 py-2 text-[13px] text-emerald-300">
              <Check size={16} /> 合格！「説明できた」を付与しました
            </div>
          )}
          {passed === false && (
            <div className="rounded-xl bg-rose-500/10 px-3 py-2 text-center text-[12px] text-rose-300">
              今回は見送り。フィードバックを参考に読み直して再挑戦を
            </div>
          )}
        </div>

        {/* 入力 */}
        <div className="border-t border-slate-800 p-3">
          {passed === true ? (
            <button type="button" onClick={onClose}
              className="w-full rounded-xl bg-emerald-600 py-2.5 text-sm font-semibold text-white">
              閉じる
            </button>
          ) : (
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
                }}
                rows={2}
                placeholder="自分の言葉で説明… (⌘+Enterで送信)"
                disabled={turn.isPending}
                className="max-h-32 min-h-[44px] flex-1 resize-none rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-[13px] text-slate-100 placeholder:text-slate-600 focus:border-amber-500/60 focus:outline-none"
              />
              <button type="button" onClick={send} disabled={turn.isPending || !input.trim()}
                className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-amber-500 text-slate-900 disabled:opacity-40">
                <Send size={18} />
              </button>
            </div>
          )}
          {passed === false && (
            <button type="button" onClick={() => { setPassed(null); setInput(""); }}
              className="mt-2 w-full text-[11px] text-slate-500 hover:text-slate-300">
              続けて説明する
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

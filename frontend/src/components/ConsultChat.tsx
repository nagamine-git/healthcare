import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type ChatMsg } from "../lib/api";
import { Panel } from "./ui/cockpit";
import { ChatMarkdown } from "./ChatMarkdown";

const EXAMPLES = [
  "朝のホエイ・難消化性デキストリン・粉飴・コーヒー・食塩・マルチビタミン、理想体型への科学的ベスト分量は?",
  "今の体組成とコンディションを見て、今いちばん効く改善は?",
  "睡眠と自律神経の最近の傾向から、今夜やるべきことは?",
];

/** 全データを文脈にしたAI相談チャット(マルチターン・履歴はクライアント保持)。 */
export function ConsultChat() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  // 他画面からの文脈付き深リンク (#consult?prefill=...) を初期入力として消費する
  useEffect(() => {
    const m = window.location.hash.match(/^#consult\?prefill=(.+)$/);
    if (m) {
      try {
        setInput(decodeURIComponent(m[1]));
      } catch {
        /* 不正なエンコードは無視 */
      }
      window.location.hash = "#consult"; // 再訪時に再注入しない
    }
  }, []);

  const send = useMutation({
    mutationFn: (msgs: ChatMsg[]) => api.consult(msgs),
    onSuccess: (r) => {
      setMessages((m) => [...m, { role: "assistant", content: r.reply }]);
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    },
    onError: () =>
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "⚠ 応答に失敗しました。少し待って再試行してください。" },
      ]),
  });

  const submit = (text: string) => {
    const t = text.trim();
    if (!t || send.isPending) return;
    const next: ChatMsg[] = [...messages, { role: "user", content: t }];
    setMessages(next);
    setInput("");
    send.mutate(next);
    setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  return (
    <Panel title="AI 相談 — あなたの全データを踏まえて答えます">
      {messages.length === 0 && (
        <div className="space-y-2">
          <p className="text-sm text-ink-dim">
            健康・体づくり／お金・資産／仕事・学習まで、あなたの全データを文脈に、実データの数字で
            具体的に答えます(健康面は診断・処方ではありません)。
          </p>
          <div className="space-y-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => submit(ex)}
                className="block w-full rounded-lg border border-hairline bg-hull/40 p-2 text-left text-xs text-ink-dim transition-colors hover:border-prog-500 hover:text-ink"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      )}

      {messages.length > 0 && (
        <div className="space-y-3">
          {messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "text-right" : ""}>
              <div
                className={`inline-block max-w-[92%] rounded-xl px-3 py-2 text-left text-sm ${
                  m.role === "user"
                    ? "bg-prog-700 text-ink"
                    : "border border-hairline bg-hull text-ink"
                }`}
              >
                {m.role === "user" ? m.content : <ChatMarkdown content={m.content} />}
              </div>
            </div>
          ))}
          {send.isPending && <p className="text-xs text-ink-faint">考え中…</p>}
          <div ref={endRef} />
        </div>
      )}

      <div className="mt-3 flex items-end gap-2 border-t border-hairline pt-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(input);
          }}
          rows={2}
          placeholder="質問を入力(⌘/Ctrl+Enter で送信)。例: 朝のサプリの最適分量は?"
          className="flex-1 rounded-lg bg-panel px-2 py-1.5 text-sm text-ink"
        />
        <button
          onClick={() => submit(input)}
          disabled={send.isPending || !input.trim()}
          className="rounded-lg bg-act px-3 py-2 text-sm font-medium text-void hover:bg-act-300 disabled:opacity-40"
        >
          送信
        </button>
      </div>
    </Panel>
  );
}

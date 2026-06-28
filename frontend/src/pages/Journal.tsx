import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Button, Panel } from "../components/ui/cockpit";
import { CheckinCard } from "../components/CheckinCard";
import { kindLabel } from "../lib/labels";

const WD = ["日", "月", "火", "水", "木", "金", "土"];

function fmtHeader(dateStr: string): string {
  // 26.06.27(土) 00:04
  const now = new Date();
  const base = dateStr ? new Date(dateStr + "T00:00:00") : now;
  const yy = String(base.getFullYear()).slice(2);
  const mm = String(base.getMonth() + 1).padStart(2, "0");
  const dd = String(base.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const mi = String(now.getMinutes()).padStart(2, "0");
  return `${yy}.${mm}.${dd}(${WD[base.getDay()]}) ${hh}:${mi}`;
}

function Heading({ children }: { children: ReactNode }) {
  return (
    <div className="mt-3 border-b border-hairline pb-1 text-xs font-semibold tracking-wider text-ink-dim">
      {children}
    </div>
  );
}

export function JournalPage({ onBack }: { onBack: () => void }) {
  const life = useQuery({ queryKey: ["life-tree"], queryFn: api.lifeTree });
  const today = useQuery({ queryKey: ["today"], queryFn: () => api.today(null), retry: false });
  const garden = useQuery({ queryKey: ["garden"], queryFn: api.garden, retry: false });
  const cal = useQuery({ queryKey: ["journal-cal"], queryFn: api.journalCalendar, retry: false });
  const move = useMutation({ mutationFn: () => api.becomingOneMove() });
  const [openEvent, setOpenEvent] = useState<string | null>(null);

  const dateStr = today.data?.date ?? "";
  const themeKeyword = garden.data?.weakest_hint?.name
    ?? life.data?.capitals.find((c) => c.key === life.data?.focus_capital)?.label
    ?? "—";
  const winning = move.data?.move ?? null;
  const winTheme = move.data?.theme ?? themeKeyword;
  const condition = today.data?.score?.total ?? null;
  const alerts = (today.data?.alerts ?? []).filter((a) => a.severity !== "info");
  const caps = life.data?.capitals ?? [];
  // 今日のボトルネック = 最低ラインを割った領域の最弱(無ければ全体の最弱)。
  const ach = (c: { achievement: number | null }) => c.achievement ?? 999;
  const bottleneck =
    [...caps].filter((c) => c.breach).sort((a, b) => ach(a) - ach(b))[0] ??
    [...caps].sort((a, b) => ach(a) - ach(b))[0];
  const manualSet = new Set(
    (garden.data?.catalog ?? []).filter((c) => c.source === "manual").map((c) => c.kind),
  );
  const bnActions = (bottleneck?.kinds ?? []).filter((k) => manualSet.has(k)).slice(0, 2);

  // スケジュール: チェックイン(今)〜「自由時間の終わり」(就寝準備の開始)まで。
  // 残り時間が長いほど粗い間隔(3h/2h/1h)。就寝準備以降は何もできない前提で除外。
  const now = new Date();
  const nowH = now.getHours() + now.getMinutes() / 60;
  const tp = today.data?.tonight_plan;
  const hm = (s?: string) =>
    s && s.length >= 5 ? parseInt(s.slice(0, 2), 10) + parseInt(s.slice(3, 5), 10) / 60 : null;
  // 自由時間の終わり = 入浴開始(就寝準備の入口)。無ければ就寝1時間前。
  let freeEnd = hm(tp?.bath_start) ?? (hm(tp?.bedtime) ?? 23) - 1;
  if (freeEnd <= nowH) freeEnd += 24;
  const remaining = freeEnd - nowH;
  const interval = remaining < 8 ? 1 : remaining < 12 ? 2 : 3;
  const blocks: number[] = [];
  for (let h = Math.floor(nowH); h < freeEnd; h += interval) blocks.push(h);
  const evByBlock = new Map<number, { summary: string; hour: number; minute: number }[]>();
  for (const e of cal.data?.events ?? []) {
    const eh = e.hour < Math.floor(nowH) ? e.hour + 24 : e.hour;
    if (eh >= freeEnd || blocks.length === 0 || eh < blocks[0]) continue;
    let b = blocks[0];
    for (const x of blocks) if (x <= eh) b = x;
    (evByBlock.get(b) ?? evByBlock.set(b, []).get(b)!).push({
      summary: e.summary, hour: e.hour, minute: e.minute,
    });
  }
  const freeEndDisp = Math.round(freeEnd) % 24;

  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold text-ink">今日の紙</h1>
      <p className="text-xs text-ink-faint">手書きノートに写して使う。アプリは候補を出すだけ。</p>

      <Panel>
        <div className="font-mono text-sm leading-relaxed text-ink">
          <div className="text-base font-bold">{fmtHeader(dateStr)}</div>

          <Heading>感謝・話したこと・今日のテーマ</Heading>
          <div className="mt-1 space-y-0.5 text-ink-faint">
            <div>感謝する人: <span className="text-ink-faint/40">________</span></div>
            <div>話した人: <span className="text-ink-faint/40">________</span></div>
            {/* テーマ(伸びしろ)と 勝ちタスク を別行に。勝ちタスク = 今日これだけは、の一手。*/}
            <div className="flex items-start gap-2">
              <div className="flex-1 space-y-0.5 text-ink">
                <div>
                  <span className="text-ink-faint">テーマ: </span>
                  <span className="font-semibold text-prog-300">{winTheme}</span>
                </div>
                <div>
                  <span className="text-ink-faint">勝ちタスク: </span>
                  {winning ? (
                    <span className="text-act-300">☐ {winning}</span>
                  ) : (
                    <span className="text-ink-faint/60">☐ (候補を出す →)</span>
                  )}
                </div>
              </div>
              <Button variant="subtle" disabled={move.isPending} onClick={() => move.mutate()}>
                {move.isPending ? "生成中…" : winning ? "別案" : "出す"}
              </Button>
            </div>
            <div className="text-[10px] text-ink-faint/60">
              勝ちタスクを早く片付けるほど“今日は勝ち”。テーマ・タスクは紙で自分の言葉に書き換えてOK。
            </div>
          </div>

          <Heading>スケジュール(自由時間 {interval}h刻み / ○=予定)</Heading>
          <div className="mt-1 space-y-0.5">
            {blocks.map((h) => {
              const evs = evByBlock.get(h) ?? [];
              return (
                <div key={h} className="flex gap-2">
                  <span className="w-6 shrink-0 tabular-nums text-ink-faint">{h % 24}</span>
                  {evs.length > 0 ? (
                    <span className="min-w-0 flex-1 space-y-0.5">
                      {evs.map((ev, i) => (
                        <button
                          key={i}
                          onClick={() => setOpenEvent(ev.summary)}
                          className="block max-w-full truncate text-left text-prog-300"
                          title={ev.summary}
                        >
                          ○ {String(ev.hour).padStart(2, "0")}:{String(ev.minute).padStart(2, "0")}{" "}
                          {ev.summary}
                        </button>
                      ))}
                    </span>
                  ) : (
                    <span className="text-ink-faint/40">—</span>
                  )}
                </div>
              );
            })}
            <div className="mt-1 text-ink-faint/60">🌙 {freeEndDisp}時〜 就寝準備(自由時間はここまで)</div>
          </div>
        </div>
      </Panel>

      {/* 今日の調子(5段階)— 既存の主観チェックイン */}
      <CheckinCard />

      {openEvent && (
        <div className="rounded-lg border border-prog-700 bg-hull p-3 text-sm text-ink">
          {openEvent}
          <button onClick={() => setOpenEvent(null)} className="ml-2 text-xs text-ink-faint">
            閉じる
          </button>
        </div>
      )}

      {(bottleneck || alerts.length > 0 || condition !== null) && (
        <Panel title="今日 意識する線(アプリからの読み出し)">
          {condition !== null && (
            <p className="text-sm text-ink-dim">
              コンディション <span className="telemetry-num text-prog-300">{Math.round(condition)}</span>
              {condition < 50 && <span className="ml-1 text-act-300">— 負荷を下げる</span>}
            </p>
          )}
          {alerts.map((a) => (
            <p key={a.code} className="mt-1 text-sm text-risk">⚠ {a.title} — {a.action}</p>
          ))}
          {bottleneck && (
            <p className="mt-1 text-sm text-ink-dim">
              ボトルネック <span className="text-act-300">{bottleneck.label}</span>
              <span className="ml-1 telemetry-num text-ink-faint">
                {Math.round(bottleneck.achievement ?? 0)}
              </span>
              {bnActions.length > 0 && (
                <span className="text-ink-faint">
                  {" "}— 今日は {bnActions.map(kindLabel).join("か")} を一つ
                </span>
              )}
            </p>
          )}
        </Panel>
      )}

      <JournalArchive />
    </div>
  );
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/** 手書きジャーナルの写真→文字起こし(要確認・修正)→ 保存・アーカイブ。 */
function JournalArchive() {
  const qc = useQueryClient();
  const entries = useQuery({ queryKey: ["journal-entries"], queryFn: api.journalEntries });
  const [draft, setDraft] = useState("");
  const [source, setSource] = useState<"text" | "image">("text");
  const [logged, setLogged] = useState(false);

  const transcribe = useMutation({
    mutationFn: async (file: File) => {
      const b64 = await fileToBase64(file);
      return api.journalTranscribe(b64, file.type || "image/png");
    },
    onSuccess: (r) => {
      setDraft(r.text);
      setSource("image");
    },
  });
  const save = useMutation({
    mutationFn: () => api.journalEntryPut({ text: draft, source }),
    onSuccess: (r) => {
      setDraft("");
      setSource("text");
      setLogged(r.journaling_logged);
      qc.invalidateQueries({ queryKey: ["journal-entries"] });
      // 控え保存でジャーナリングが「やったこと」になる → 庭/今日/人生木を更新。
      qc.invalidateQueries({ queryKey: ["garden"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["life-tree"] });
    },
  });
  const del = useMutation({
    mutationFn: (date: string) => api.journalEntryDelete(date),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal-entries"] }),
  });

  return (
    <Panel title="手書きを取り込む / 控え">
      <label className="block">
        <span className="telemetry-label">📷 手書きの写真から文字起こし</span>
        <input
          type="file"
          accept="image/*"
          disabled={transcribe.isPending}
          onChange={(e) => e.target.files?.[0] && transcribe.mutate(e.target.files[0])}
          className="mt-1 block w-full text-xs text-ink-dim file:mr-2 file:rounded file:border-0 file:bg-act file:px-3 file:py-1 file:text-void"
        />
      </label>
      {transcribe.isPending && <p className="mt-1 text-xs text-ink-faint">文字起こし中…</p>}
      {transcribe.isError && <p className="mt-1 text-xs text-risk">読み取れませんでした</p>}

      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={6}
        placeholder="ここに文字起こし結果が入ります。手書きは誤読しやすいので必ず確認・修正してから保存。直接入力もOK。"
        className="mt-2 w-full rounded bg-panel px-2 py-1 font-mono text-xs text-ink"
      />
      <p className="mt-1 text-[10px] text-ink-faint">
        ⚠ 自動文字起こしは精度が低い前提。`[?]` は読めなかった箇所。必ず確認・修正を。
      </p>
      <div className="mt-2 flex items-center gap-2">
        <Button variant="primary" disabled={save.isPending || !draft.trim()} onClick={() => save.mutate()}>
          {save.isPending ? "保存中…" : "今日の控えとして保存"}
        </Button>
        {save.isSuccess && (
          <span className="text-xs text-prog-300">
            ✓ 保存{logged ? " ・ ジャーナリングを記録" : "(ジャーナリングは記録済み)"}
          </span>
        )}
      </div>

      {(entries.data?.entries.length ?? 0) > 0 && (
        <div className="mt-3 space-y-2 border-t border-hairline pt-2">
          {entries.data!.entries.map((e) => (
            <div key={e.date} className="text-xs">
              <div className="flex items-center justify-between">
                <span className="telemetry-num text-ink-dim">{e.date}</span>
                <button onClick={() => del.mutate(e.date)} className="text-ink-faint hover:text-risk">
                  削除
                </button>
              </div>
              <pre className="mt-0.5 whitespace-pre-wrap font-mono text-[11px] text-ink-faint">{e.text}</pre>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

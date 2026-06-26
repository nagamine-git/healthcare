import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import {
  api,
  type ChatMsg,
  type IdentityGapDimension,
  type IdentityRecommendation,
  type IdentityResponse,
  type SjtAssessed,
} from "../lib/api";

type Props = { onBack: () => void };

function alignColor(v: number | null): string {
  if (v == null) return "#94a3b8";
  const r = Math.max(0, Math.min(1, v / 100));
  const hue = r < 0.5 ? 5 + 90 * (r / 0.5) : 50 + 90 * ((r - 0.5) / 0.5);
  return `hsl(${Math.round(hue)} 70% 55%)`;
}

export function IdentityPage({ onBack }: Props) {
  const q = useQuery({ queryKey: ["identity"], queryFn: api.identity });
  const [reflectTarget, setReflectTarget] = useState<IdentityRecommendation | null>(null);

  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4 text-ink">
      <header className="safe-area-top flex items-center justify-between pb-1">
        <button
          onClick={onBack}
          className="rounded-lg px-2 py-1 text-sm text-slate-400 hover:text-slate-200"
        >
          ← 戻る
        </button>
        <h1 className="text-sm tracking-wider text-slate-300">
          Compass <span className="text-[10px] text-slate-500">価値観 × マインドセット</span>
        </h1>
        <span className="w-12" />
      </header>

      {q.isLoading && <p className="text-sm text-slate-500">読み込み中…</p>}
      {q.isError && <p className="text-sm text-rose-400">取得に失敗しました</p>}
      {q.data && (
        <>
          <OverviewCard data={q.data} />
          <RadarPanel data={q.data} layer="mindset" title="マインドセット層" />
          <RadarPanel data={q.data} layer="values" title="価値観層" />
          <GapList dims={q.data.report.dimensions} weakest={q.data.report.weakest} />
          <SjtPanel />
          <DecisionLogPanel recent={q.data.recent_logs} />
          <RecommendationsPanel
            recs={q.data.recommendations}
            onReflect={(r) => setReflectTarget(r)}
          />
          {reflectTarget && (
            <ReflectionPanel
              target={reflectTarget}
              onClose={() => setReflectTarget(null)}
            />
          )}
          <IntentionsPanel intentions={q.data.intentions} />
          <LibraryPanel library={q.data.library} />
        </>
      )}
    </div>
  );
}

function Card({ children, title, subtitle }: { children: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/70 p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm tracking-wide text-slate-300">{title}</h2>
        {subtitle && <span className="text-[10px] text-slate-500">{subtitle}</span>}
      </div>
      {children}
    </section>
  );
}

function OverviewCard({ data }: { data: IdentityResponse }) {
  const { report } = data;
  return (
    <Card title={`理想プロファイル: ${report.archetype_name ?? "—"}`} subtitle={data.date}>
      <div className="flex flex-wrap items-end gap-6">
        <Metric label="全体整合度" value={report.overall} />
        <Metric label="マインドセット" value={report.layers.mindset} />
        <Metric label="価値観" value={report.layers.values} />
      </div>
      <p className="text-[11px] leading-relaxed text-slate-500">
        「欠陥を直す」ではなく、選んだ価値に沿って一歩進むための地図です。弱い次元に効く作品を観て、
        小さな実行意図(if-then)に変えていきます。
      </p>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <div className="text-[10px] tracking-wider text-slate-500">{label}</div>
      <div className="text-3xl font-light tabular-nums" style={{ color: alignColor(value) }}>
        {value != null ? Math.round(value) : "--"}
      </div>
    </div>
  );
}

function RadarPanel({
  data,
  layer,
  title,
}: {
  data: IdentityResponse;
  layer: "values" | "mindset";
  title: string;
}) {
  const rows = useMemo(
    () =>
      data.report.dimensions
        .filter((d) => d.layer === layer)
        .map((d) => ({
          axis: d.name,
          score: d.current ?? 0,
          target: d.target,
        })),
    [data, layer],
  );
  const hasData = rows.some((r) => r.score > 0);
  return (
    <Card title={title} subtitle="現状(実線) vs 理想(点線)">
      <div className="h-72">
        {rows.length >= 3 ? (
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={rows} outerRadius="72%">
              <PolarGrid stroke="#1e293b" />
              <PolarAngleAxis dataKey="axis" tick={{ fill: "#cbd5e1", fontSize: 11 }} />
              <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: "#475569", fontSize: 9 }} stroke="#334155" tickCount={5} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", fontSize: 12 }}
                formatter={(v: number, name: string) => [Math.round(v).toString(), name === "target" ? "理想" : "現状"]}
              />
              <Radar name="target" dataKey="target" stroke="#64748b" fill="none" strokeWidth={1} strokeDasharray="3 3" isAnimationActive={false} />
              <Radar name="score" dataKey="score" stroke="#34d399" fill="#34d399" fillOpacity={0.22} isAnimationActive={false} />
            </RadarChart>
          </ResponsiveContainer>
        ) : null}
      </div>
      {!hasData && (
        <p className="text-[11px] text-amber-400/70">
          まだ現在地が測れていません。下の「状況判断テスト(SJT)」を 1 回やると現在地が出ます。
        </p>
      )}
    </Card>
  );
}

function GapList({ dims, weakest }: { dims: IdentityGapDimension[]; weakest: string[] }) {
  const order = useMemo(() => {
    const rank = new Map(weakest.map((id, i) => [id, i]));
    return [...dims].sort((a, b) => (rank.get(a.id) ?? 999) - (rank.get(b.id) ?? 999));
  }, [dims, weakest]);
  return (
    <Card title="ギャップ(伸びしろの大きい順)">
      <div className="space-y-2">
        {order.map((d) => {
          const ratio = d.proximity != null ? d.proximity / 100 : 0;
          return (
            <div key={d.id} className="space-y-1">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-slate-300">{d.name}</span>
                <span className="tabular-nums text-slate-400">
                  {d.current != null ? (
                    <span style={{ color: alignColor(d.current) }}>{Math.round(d.current)}</span>
                  ) : (
                    <span className="text-amber-400/70">--</span>
                  )}
                  <span className="text-slate-600"> / {Math.round(d.target)}</span>
                  {d.gap != null && d.gap > 0 && (
                    <span className="ml-1 text-[10px] text-slate-500">(−{Math.round(d.gap)})</span>
                  )}
                </span>
              </div>
              <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div className="h-full rounded-full" style={{ width: `${Math.round(ratio * 100)}%`, background: alignColor(d.current) }} />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function SjtPanel() {
  const qc = useQueryClient();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [scenario, setScenario] = useState<{ situation: string; options: string[] } | null>(null);
  const [assessed, setAssessed] = useState<SjtAssessed[]>([]);
  const [done, setDone] = useState(false);
  const [started, setStarted] = useState(false);

  const turn = useMutation({
    mutationFn: (msgs: ChatMsg[]) => api.identitySjtTurn(msgs),
    onSuccess: (res) => {
      setAssessed(res.assessed);
      setDone(res.done);
      setScenario(res.next_scenario.situation ? res.next_scenario : null);
    },
  });
  const commit = useMutation({
    mutationFn: () => {
      const result: Record<string, number> = {};
      for (const a of assessed) result[a.dimension_id] = a.score;
      return api.identitySjtCommit(result);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["identity"] });
      setStarted(false);
      setMessages([]);
      setScenario(null);
      setAssessed([]);
      setDone(false);
    },
  });

  const start = () => {
    setStarted(true);
    turn.mutate([]);
  };
  const choose = (opt: string) => {
    if (!scenario) return;
    const next: ChatMsg[] = [
      ...messages,
      { role: "assistant", content: `${scenario.situation}\n選択肢: ${scenario.options.join(" / ")}` },
      { role: "user", content: opt },
    ];
    setMessages(next);
    setScenario(null);
    turn.mutate(next);
  };

  return (
    <Card title="状況判断テスト(SJT)" subtitle={`${assessed.length} 次元 測定済み`}>
      {!started ? (
        <button onClick={start} className="rounded-lg bg-emerald-600/80 px-4 py-2 text-sm hover:bg-emerald-600">
          測定を始める
        </button>
      ) : (
        <div className="space-y-3">
          {turn.isPending && <p className="text-sm text-slate-500">考え中…</p>}
          {scenario && !turn.isPending && (
            <div className="space-y-2">
              <p className="text-sm leading-relaxed text-slate-200">{scenario.situation}</p>
              <div className="grid gap-2">
                {scenario.options.map((opt, i) => (
                  <button
                    key={i}
                    onClick={() => choose(opt)}
                    className="rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-left text-sm hover:border-emerald-600"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            </div>
          )}
          {(done || (!scenario && !turn.isPending && assessed.length > 0)) && (
            <div className="space-y-2 border-t border-slate-800 pt-3">
              <p className="text-xs text-slate-400">
                {done ? "全次元を測り終えました。" : "ここまでの結果を保存できます。"}
              </p>
              <button
                onClick={() => commit.mutate()}
                disabled={commit.isPending}
                className="rounded-lg bg-emerald-600/80 px-4 py-2 text-sm hover:bg-emerald-600 disabled:opacity-50"
              >
                {commit.isPending ? "保存中…" : "現在地として保存"}
              </button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function DecisionLogPanel({
  recent,
}: {
  recent: IdentityResponse["recent_logs"];
}) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const post = useMutation({
    mutationFn: (t: string) => api.identityDecisionLog(t),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["identity"] });
    },
  });
  return (
    <Card title="意思決定ログ" subtitle="今日こう動いた、を一言">
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="例: 担当外だが障害対応を引き受けた"
          className="flex-1 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm outline-none focus:border-emerald-600"
        />
        <button
          onClick={() => text.trim() && post.mutate(text.trim())}
          disabled={post.isPending || !text.trim()}
          className="rounded-lg bg-emerald-600/80 px-3 py-2 text-sm hover:bg-emerald-600 disabled:opacity-50"
        >
          記録
        </button>
      </div>
      <div className="space-y-2">
        {recent.map((r) => (
          <div key={r.id} className="rounded-lg bg-slate-800/40 px-3 py-2">
            <div className="text-xs text-slate-300">{r.text}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {r.inferred.map((s, i) => (
                <span
                  key={i}
                  className="rounded-full bg-slate-700/60 px-2 py-0.5 text-[10px] text-slate-300"
                  title={s.rationale}
                >
                  {s.dimension_id} {s.signal > 0 ? "+" : ""}{s.signal.toFixed(1)}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

const CATEGORY_LABEL: Record<IdentityRecommendation["category"], string> = {
  rewatch: "見返す",
  watchlist: "これから観る",
  new: "新規発見",
};
const CATEGORY_BADGE: Record<IdentityRecommendation["category"], string> = {
  rewatch: "bg-amber-600/30 text-amber-200",
  watchlist: "bg-sky-600/30 text-sky-200",
  new: "bg-emerald-600/30 text-emerald-200",
};
const KIND_LABEL: Record<string, string> = {
  film: "🎬 映画",
  tv: "📺 ドラマ",
  manga: "📖 マンガ",
  book: "📚 本",
};
const KINDS = ["film", "tv", "manga", "book"] as const;
type KindFilter = "all" | (typeof KINDS)[number];

function RecommendationsPanel({
  recs,
  onReflect,
}: {
  recs: IdentityRecommendation[];
  onReflect: (r: IdentityRecommendation) => void;
}) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"all" | IdentityRecommendation["category"]>("all");
  const [kind, setKind] = useState<KindFilter>("all");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const toggleExpand = (id: number) =>
    setExpanded((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const suggest = useMutation({
    mutationFn: () => api.identitySuggestNew(10),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["identity"] }),
  });

  // 種別フィルタを先に適用した集合でカテゴリ件数を数える (見えている数と一致させる)。
  const byKind = kind === "all" ? recs : recs.filter((r) => r.kind === kind);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: byKind.length, rewatch: 0, watchlist: 0, new: 0 };
    for (const r of byKind) c[r.category] = (c[r.category] ?? 0) + 1;
    return c;
  }, [byKind]);
  const kindCounts = useMemo(() => {
    const c: Record<string, number> = { all: recs.length, film: 0, tv: 0, manga: 0, book: 0 };
    for (const r of recs) c[r.kind] = (c[r.kind] ?? 0) + 1;
    return c;
  }, [recs]);
  const shown = byKind.filter((r) => filter === "all" || r.category === filter);
  const maxScore = Math.max(...shown.map((x) => x.score), 0.0001);

  return (
    <Card title="おすすめ作品" subtitle="レバレッジ順(弱点 × 重要度で選定)">
      <div className="flex flex-wrap items-center gap-1.5">
        {(["all", "rewatch", "watchlist", "new"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1 text-[11px] ${
              filter === f ? "bg-slate-200 text-slate-900" : "bg-slate-800/60 text-slate-300"
            }`}
          >
            {f === "all" ? "すべて" : CATEGORY_LABEL[f]} ({counts[f] ?? 0})
          </button>
        ))}
        <button
          onClick={() => suggest.mutate()}
          disabled={suggest.isPending}
          className="ml-auto rounded-lg border border-emerald-700/60 px-3 py-1 text-[11px] text-emerald-300 hover:bg-emerald-900/30 disabled:opacity-50"
        >
          {suggest.isPending ? "提案生成中…" : "＋ リスト外を提案"}
        </button>
      </div>

      {/* メディア種別フィルタ (映画/ドラマ/マンガ/本) */}
      <div className="flex flex-wrap items-center gap-1.5">
        {(["all", ...KINDS] as const).map((k) => (
          <button
            key={k}
            onClick={() => setKind(k)}
            className={`rounded-full px-2.5 py-0.5 text-[11px] ${
              kind === k ? "bg-slate-200 text-slate-900" : "bg-slate-800/60 text-slate-400"
            }`}
          >
            {k === "all" ? "全種別" : KIND_LABEL[k]} ({kindCounts[k] ?? 0})
          </button>
        ))}
      </div>

      {recs.length === 0 ? (
        <p className="text-[11px] text-slate-500">
          作品を取り込み・タグ付けするか、「＋ リスト外を提案」で推薦が出ます。
        </p>
      ) : (
        <div className="space-y-2">
          {shown.map((r, i) => (
            <div key={r.media_item_id} className="flex items-start justify-between gap-3 rounded-lg bg-slate-800/40 px-3 py-2">
              <div className="min-w-0 flex-1 space-y-1">
                {/* バッジ行 */}
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] font-semibold tabular-nums text-slate-400">#{i + 1}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[9px] ${CATEGORY_BADGE[r.category]}`}>
                    {CATEGORY_LABEL[r.category]}
                  </span>
                  <span className="text-[10px] text-slate-400">{KIND_LABEL[r.kind] ?? r.kind}</span>
                  {r.rating != null && <span className="text-[10px] text-amber-300/80">★{r.rating}</span>}
                </div>
                {/* タイトル: 2行表示、クリックで全文 */}
                <button
                  onClick={() => toggleExpand(r.media_item_id)}
                  className="block w-full text-left text-sm text-slate-200"
                  title={r.title}
                  style={
                    expanded.has(r.media_item_id)
                      ? undefined
                      : { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }
                  }
                >
                  {r.title} {r.year && <span className="text-[10px] text-slate-500">({r.year})</span>}
                </button>
                <div className="text-[10px] text-slate-500">{r.reason}</div>
                {/* レバレッジ相対バー (リスト内の最大を 100%) */}
                <div className="h-1 w-full max-w-[220px] overflow-hidden rounded-full bg-slate-700/50">
                  <div
                    className="h-full rounded-full bg-emerald-400/70"
                    style={{ width: `${Math.round((r.score / maxScore) * 100)}%` }}
                  />
                </div>
                {r.imdb_url && (
                  <a
                    href={r.imdb_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[10px] text-amber-300/90 hover:text-amber-200"
                    title="IMDbで評価して「観た記録」にする"
                  >
                    <span className="rounded bg-amber-400/20 px-1 font-bold tracking-tight">IMDb</span>
                    で評価↗
                  </a>
                )}
              </div>
              <button
                onClick={() => onReflect(r)}
                className="shrink-0 rounded-lg border border-slate-700 px-3 py-1 text-xs hover:border-emerald-600"
              >
                {(() => {
                  const read = r.kind === "book" || r.kind === "manga";
                  if (r.category === "rewatch") return read ? "再読→内省" : "見返す→内省";
                  return read ? "読んだ→内省" : "観た→内省";
                })()}
              </button>
            </div>
          ))}
          {shown.length === 0 && (
            <p className="text-[11px] text-slate-500">この区分の作品はまだありません。</p>
          )}
        </div>
      )}
    </Card>
  );
}

function ReflectionPanel({
  target,
  onClose,
}: {
  target: IdentityRecommendation;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [question, setQuestion] = useState<string>("");
  const [answer, setAnswer] = useState("");
  const [intention, setIntention] = useState<{ text: string; dim: string } | null>(null);
  const [started, setStarted] = useState(false);

  const reflect = useMutation({
    mutationFn: (msgs: ChatMsg[]) => api.identityReflect(target.media_item_id, msgs),
    onSuccess: (res) => {
      if (res.intention) {
        setIntention({ text: res.intention, dim: res.intention_dimension_id });
        setQuestion("");
      } else {
        setQuestion(res.next_question);
      }
    },
  });
  const save = useMutation({
    mutationFn: () =>
      api.identitySaveIntention(target.media_item_id, {
        intention: intention?.text ?? "",
        dimension_id: intention?.dim || undefined,
        reflection: messages.map((m) => m.content).join("\n"),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["identity"] });
      onClose();
    },
  });

  const begin = () => {
    setStarted(true);
    reflect.mutate([]);
  };
  const send = () => {
    if (!answer.trim()) return;
    const next: ChatMsg[] = [
      ...messages,
      ...(question ? [{ role: "assistant" as const, content: question }] : []),
      { role: "user" as const, content: answer.trim() },
    ];
    setMessages(next);
    setAnswer("");
    reflect.mutate(next);
  };

  return (
    <Card title={`内省: ${target.title}`} subtitle="作品 → 内省 → 実行意図">
      {!started ? (
        <button onClick={begin} className="rounded-lg bg-emerald-600/80 px-4 py-2 text-sm hover:bg-emerald-600">
          内省を始める
        </button>
      ) : (
        <div className="space-y-3">
          {reflect.isPending && <p className="text-sm text-slate-500">考え中…</p>}
          {question && !intention && !reflect.isPending && (
            <div className="space-y-2">
              <p className="text-sm leading-relaxed text-slate-200">{question}</p>
              <div className="flex gap-2">
                <input
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && send()}
                  className="flex-1 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm outline-none focus:border-emerald-600"
                />
                <button onClick={send} className="rounded-lg bg-emerald-600/80 px-3 py-2 text-sm hover:bg-emerald-600">
                  返答
                </button>
              </div>
            </div>
          )}
          {intention && (
            <div className="space-y-2 border-t border-slate-800 pt-3">
              <div className="text-[10px] tracking-wider text-slate-500">実行意図(if-then)</div>
              <p className="rounded-lg bg-slate-800/60 px-3 py-2 text-sm text-emerald-200">{intention.text}</p>
              <div className="flex gap-2">
                <button
                  onClick={() => save.mutate()}
                  disabled={save.isPending}
                  className="rounded-lg bg-emerald-600/80 px-4 py-2 text-sm hover:bg-emerald-600 disabled:opacity-50"
                >
                  {save.isPending ? "保存中…" : "これを実行する"}
                </button>
                <button onClick={onClose} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-400">
                  やめる
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function IntentionsPanel({
  intentions,
}: {
  intentions: IdentityResponse["intentions"];
}) {
  const qc = useQueryClient();
  const fb = useMutation({
    mutationFn: ({ id, done, rating }: { id: number; done: boolean; rating: number }) =>
      api.identityIntentionFeedback(id, done, rating),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["identity"] }),
  });
  if (intentions.length === 0) return null;
  return (
    <Card title="実行意図の振り返り" subtitle="効いたか検証する">
      <div className="space-y-2">
        {intentions.map((it) => (
          <div key={it.media_item_id} className="rounded-lg bg-slate-800/40 px-3 py-2">
            <div className="text-sm text-emerald-200">{it.intention}</div>
            <div className="mt-0.5 text-[10px] text-slate-500">{it.title}</div>
            <div className="mt-2 flex items-center gap-2">
              <button
                onClick={() => fb.mutate({ id: it.media_item_id, done: !it.done, rating: it.rating })}
                className={`rounded-lg px-2 py-1 text-xs ${it.done ? "bg-emerald-600/70" : "border border-slate-700 text-slate-400"}`}
              >
                {it.done ? "✓ 実行した" : "実行した"}
              </button>
              <button
                onClick={() => fb.mutate({ id: it.media_item_id, done: it.done, rating: it.rating === 1 ? 0 : 1 })}
                className={`rounded-lg px-2 py-1 text-xs ${it.rating === 1 ? "bg-emerald-600/70" : "border border-slate-700 text-slate-400"}`}
              >
                👍
              </button>
              <button
                onClick={() => fb.mutate({ id: it.media_item_id, done: it.done, rating: it.rating === -1 ? 0 : -1 })}
                className={`rounded-lg px-2 py-1 text-xs ${it.rating === -1 ? "bg-rose-600/70" : "border border-slate-700 text-slate-400"}`}
              >
                👎
              </button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result ?? ""));
    fr.onerror = () => reject(fr.error);
    fr.readAsText(file);
  });
}

/** ファイル名から ratings / watchlist を推定 (IMDb の既定名に対応)。 */
function kindFromFilename(name: string): "ratings" | "watchlist" {
  return /rating/i.test(name) ? "ratings" : "watchlist";
}

function LibraryPanel({
  library,
}: {
  library: IdentityResponse["library"];
}) {
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string>("");

  const imp = useMutation({
    mutationFn: async (files: File[]) => {
      const totals = { items: 0, seen: 0, watchlist: 0 };
      for (const f of files) {
        const text = await readFileText(f);
        if (!text.trim()) continue;
        const res = await api.identityImdbImport(text, kindFromFilename(f.name));
        totals.items += res.items;
        totals.seen += res.seen;
        totals.watchlist += res.watchlist;
      }
      return totals;
    },
    onSuccess: (t) => {
      setMsg(`取込: ${t.items} 件 (seen ${t.seen} / watchlist ${t.watchlist})`);
      qc.invalidateQueries({ queryKey: ["identity"] });
    },
    onError: () => setMsg("取込に失敗しました(CSV を確認してください)"),
  });
  const [tagging, setTagging] = useState(false);
  const [tagMsg, setTagMsg] = useState("");
  const runTag = async () => {
    setTagging(true);
    setTagMsg("");
    let guard = 0;
    try {
      // 小バッチ (5件) を残り 0 になるまで自動継続。各件は個別コミット済みなので
      // 途中で止まっても無駄にならない。全件失敗が続くループは guard で止める。
      while (guard < 300) {
        guard += 1;
        const res = await api.identityTagUntagged(5);
        qc.invalidateQueries({ queryKey: ["identity"] });
        if (res.remaining <= 0) {
          setTagMsg("タグ付け完了");
          break;
        }
        setTagMsg(`タグ付け中… 残り ${res.remaining}`);
        if (res.tagged === 0 && res.failed > 0) {
          setTagMsg(`一部失敗(残り ${res.remaining})。もう一度押すと続きから再開します`);
          break;
        }
      }
    } catch {
      setTagMsg("通信エラー。もう一度押すと続きから再開できます");
    } finally {
      setTagging(false);
      qc.invalidateQueries({ queryKey: ["identity"] });
    }
  };

  return (
    <Card title="ライブラリ取り込み" subtitle={`${library.total} 作品 / 未タグ ${library.untagged}`}>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label
            className={`cursor-pointer rounded-lg bg-emerald-600/80 px-3 py-1.5 hover:bg-emerald-600 ${
              imp.isPending ? "pointer-events-none opacity-50" : ""
            }`}
          >
            {imp.isPending ? "取込中…" : "IMDb CSV を選択"}
            <input
              type="file"
              accept=".csv,text/csv"
              multiple
              className="hidden"
              disabled={imp.isPending}
              onChange={(e) => {
                const files = Array.from(e.target.files ?? []);
                e.target.value = ""; // 同じファイルを再選択できるようにリセット
                if (files.length) {
                  setMsg("");
                  imp.mutate(files);
                }
              }}
            />
          </label>
          <button
            onClick={runTag}
            disabled={tagging || library.untagged === 0}
            className="rounded-lg border border-slate-700 px-3 py-1.5 disabled:opacity-50"
          >
            {tagging ? "タグ付け中…" : `未タグをタグ付け${library.untagged ? ` (${library.untagged})` : ""}`}
          </button>
        </div>
        {msg && <p className="text-[11px] text-emerald-300/80">{msg}</p>}
        {tagMsg && <p className="text-[11px] text-sky-300/80">{tagMsg}</p>}
        <p className="text-[10px] leading-relaxed text-slate-600">
          IMDb の Your Ratings / Watchlist ページで「Export」してダウンロードした
          <code className="mx-1 rounded bg-slate-800 px-1">ratings.csv</code>/
          <code className="mx-1 rounded bg-slate-800 px-1">WATCHLIST.csv</code>
          をそのまま選ぶだけ(複数同時可・ファイル名で自動判別)。
          マンガ・本は手動登録(API 経由)で追加できます。
        </p>
      </div>
    </Card>
  );
}

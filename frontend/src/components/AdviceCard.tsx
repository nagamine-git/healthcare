import { useState } from "react";
import { Check, ThumbsDown, ThumbsUp } from "lucide-react";
import { api } from "../lib/api";
import type {
  Advice,
  AdviceAction,
  AdvicePriority,
  ExerciseCandidate,
  ExerciseCandidatesResponse,
  GcalScheduleResult,
} from "../lib/api";

type FeedbackPatch = { action_key: string; done?: boolean; rating?: number; category?: string };
type Props = {
  advice: Advice | null;
  onRegenerate: () => void;
  onSchedule?: () => Promise<GcalScheduleResult>;
  onFeedback?: (patch: FeedbackPatch) => void;
  gcalConfigured?: boolean;
  pending?: boolean;
};

const CATEGORY_LABEL: Record<AdviceAction["category"], string> = {
  training: "筋トレ",
  cardio: "有酸素",
  recovery: "回復",
  mobility: "モビリティ",
  nutrition: "食事/水分",
  rest: "休息",
  focus: "集中力",
  other: "その他",
};

// カテゴリは slate 単色で統一 (情報過多を避ける)
const CATEGORY_BADGE = "border border-hairline bg-panel/40 text-ink-dim";

const PRIORITY_LABEL: Record<AdvicePriority, string> = {
  critical: "今すぐ",
  high: "本日中",
  mid: "推奨",
  low: "任意",
};

// 優先度は意味があるので 4 段階維持、しかし強度はおさえる
const PRIORITY_COLOR: Record<AdvicePriority, string> = {
  critical: "border border-risk/70 bg-risk/10 text-risk",
  high: "border border-act/60 bg-act/10 text-act-300",
  mid: "border border-ink-faint bg-transparent text-ink-dim",
  low: "border border-hairline bg-transparent text-ink-faint",
};

const PRIORITY_RANK: Record<AdvicePriority, number> = {
  critical: 0,
  high: 1,
  mid: 2,
  low: 3,
};

export function AdviceCard({ advice, onRegenerate, onSchedule, onFeedback, gcalConfigured, pending }: Props) {
  const feedback = advice?.feedback ?? {};
  const [scheduling, setScheduling] = useState(false);
  const [scheduleResult, setScheduleResult] = useState<GcalScheduleResult | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const handleSchedule = async () => {
    if (!onSchedule) return;
    setScheduling(true);
    setScheduleError(null);
    try {
      const r = await onSchedule();
      setScheduleResult(r);
    } catch (e) {
      setScheduleError((e as Error).message);
    } finally {
      setScheduling(false);
    }
  };

  const payload = advice?.payload ?? null;

  return (
    <div className="rounded-xl bg-gradient-to-br from-hull/80 to-panel/60 p-5 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-ink-dim">今日のフォーカス</h3>
        <div className="flex gap-2">
          <button
            onClick={onRegenerate}
            disabled={pending}
            className="rounded-full border border-ink-faint px-3 py-1 text-xs text-ink-dim hover:bg-panel disabled:opacity-50"
          >
            {pending ? "生成中..." : "再生成"}
          </button>
          {gcalConfigured && payload && payload.actions.length > 0 && (
            <button
              onClick={handleSchedule}
              disabled={scheduling}
              className="rounded-full border border-prog-700 bg-prog-900/30 px-3 py-1 text-xs text-prog-300 hover:bg-prog-900/60 disabled:opacity-50"
            >
              {scheduling ? "登録中..." : "Calendar に追加"}
            </button>
          )}
        </div>
      </div>

      {!advice ? (
        <p className="text-ink-faint">
          まだアドバイスは生成されていません。「再生成」を押すか、朝のジョブを待ってください。
        </p>
      ) : (
        <>
          {/* Headline (1行パンチライン、大きく) */}
          {payload?.headline && (
            <p className="mb-2 text-xl font-semibold leading-snug text-ink sm:text-2xl">
              {payload.headline}
            </p>
          )}

          {/* Actions list — priority 順、最初 1 件は常に展開、残りは折りたたみ */}
          {payload && payload.actions.length === 0 && (
            <p className="mt-2 text-xs text-ink-dim">
              本日推奨アクションなし。コンディション維持で OK。
            </p>
          )}
          {payload && payload.actions.length > 0 && (
            <ul className="mt-3 space-y-2">
              {(() => {
                const nowMin = nowMinutes();
                const sorted = [...payload.actions].sort(
                  (a, b) =>
                    (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9) ||
                    a.time_jst.localeCompare(b.time_jst),
                );
                // 時間窓モデル: time_jst は「推奨開始」、until_jst (無ければ
                // 開始+所要+60分の猶予) までに始めれば OK。窓内は「いまからOK」。
                // 期限超過でも carryover (水分・栄養・回復などの不足解消系) は
                // 「過ぎたからしなくていい」にはならないので、遅れ表示のまま
                // 優先度順の位置に残す。沈める (過ぎた) のは時間依存の行動だけ。
                const tagged = sorted.map((a) => {
                  const start = timeToMin(a.time_jst);
                  const deadline = a.until_jst
                    ? timeToMin(a.until_jst)
                    : start + Math.max(a.duration_min ?? 0, 0) + 60;
                  const carryover =
                    a.carryover ??
                    (a.category === "nutrition" ||
                      a.category === "recovery" ||
                      a.category === "rest" ||
                      a.priority === "critical");
                  const expired = nowMin > deadline;
                  const past = expired && !carryover;
                  const late = expired && carryover;
                  const open = !expired && nowMin >= start;
                  return { a, past, open, late };
                });
                // 実行可能 (未来・窓内・遅れても推奨) を優先度順で上に、
                // 本当に過ぎたものだけ末尾へ
                const ordered = [...tagged.filter((x) => !x.past), ...tagged.filter((x) => x.past)];
                return expanded ? ordered : ordered.slice(0, 1);
              })().map(({ a, past, open, late }, i) => (
                  <li
                    key={`${a.time_jst}-${i}`}
                    className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-xl border border-panel bg-hull/60 px-3 py-2 ${
                      past ? "opacity-45" : ""
                    }`}
                  >
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[10px] tracking-wider ${
                        PRIORITY_COLOR[a.priority] ?? PRIORITY_COLOR.mid
                      }`}
                    >
                      {PRIORITY_LABEL[a.priority] ?? a.priority}
                    </span>
                    <span
                      className={`telemetry-num text-base tabular-nums ${
                        past ? "text-ink-faint line-through" : "text-ink"
                      }`}
                    >
                      {a.time_jst}
                    </span>
                    {past && (
                      <span className="rounded-full bg-panel px-1.5 py-0.5 text-[10px] text-ink-dim">
                        過ぎた
                      </span>
                    )}
                    {open && (
                      <span className="rounded-full border border-prog-700/60 bg-prog-900/30 px-1.5 py-0.5 text-[10px] text-prog-300">
                        いまからOK{a.until_jst ? ` 〜${a.until_jst}` : ""}
                      </span>
                    )}
                    {late && (
                      <span className="rounded-full border border-act/60 bg-act-700/30 px-1.5 py-0.5 text-[10px] text-act-300">
                        遅れても推奨・いまから
                      </span>
                    )}
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] tracking-wider ${CATEGORY_BADGE}`}
                    >
                      {CATEGORY_LABEL[a.category] ?? a.category}
                    </span>
                    <span className="text-ink">{a.title}</span>
                    <span className="text-xs text-ink-faint">{a.duration_min} 分</span>
                    {a.intensity && (
                      <span className="text-xs text-ink-dim">· {a.intensity}</span>
                    )}
                    {a.why && (
                      <span className="basis-full text-xs text-ink-faint">{a.why}</span>
                    )}
                    {a.exercises && a.exercises.length > 0 && (
                      <ExerciseList exercises={a.exercises} />
                    )}
                    {a.alternative && (
                      <div className="basis-full mt-1 rounded-md border border-hairline bg-hull/50 px-2 py-1.5">
                        <div className="flex flex-wrap items-baseline gap-x-2">
                          <span className="rounded bg-panel px-1.5 py-0.5 text-[10px] font-medium text-ink-dim">
                            代替 B
                          </span>
                          <span className="text-xs text-ink">{a.alternative.title}</span>
                          {a.alternative.duration_min != null && (
                            <span className="text-[11px] text-ink-faint">
                              {a.alternative.duration_min} 分
                            </span>
                          )}
                          {a.alternative.intensity && (
                            <span className="text-[11px] text-ink-dim">
                              · {a.alternative.intensity}
                            </span>
                          )}
                        </div>
                        <p className="mt-0.5 text-[11px] text-ink-faint">{a.alternative.why}</p>
                      </div>
                    )}
                    {a.considered && a.considered.length > 0 && (
                      <details open className="basis-full mt-1 text-xs">
                        <summary className="cursor-pointer select-none font-medium text-ink-dim">
                          見送った候補 ({a.considered.length})
                        </summary>
                        <ul className="mt-1.5 space-y-1.5">
                          {a.considered.map((c, ci) => (
                            <li key={ci}
                                className="rounded-md border border-hairline bg-hull/40 px-2 py-1.5">
                              <div className="font-medium text-ink">{c.title}</div>
                              <div className="mt-0.5 text-ink-faint">見送り理由: {c.reason}</div>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                    {onFeedback && (
                      <ActionFeedback
                        fb={feedback[a.title]}
                        onDone={(done) =>
                          onFeedback({ action_key: a.title, done, category: a.category })
                        }
                        onRate={(rating) =>
                          onFeedback({ action_key: a.title, rating, category: a.category })
                        }
                      />
                    )}
                  </li>
                ))}
            </ul>
          )}

          {/* 展開トグル */}
          {payload && (payload.actions.length > 1 || payload.focus || payload.rationale) && (
            <button
              onClick={() => setExpanded((e) => !e)}
              className="mt-3 text-xs text-ink-faint hover:text-ink-dim"
            >
              {expanded
                ? "▴ 折りたたむ"
                : `▾ あと ${Math.max(0, payload.actions.length - 1)} 件 + 詳細を表示`}
            </button>
          )}

          {/* Focus と Rationale は展開時のみ */}
          {expanded && payload?.focus && (
            <p className="mt-3 text-sm leading-relaxed text-ink-dim">
              {payload.focus}
            </p>
          )}
          {expanded && payload?.rationale && (
            <p className="mt-2 text-xs leading-relaxed text-ink-faint">
              <span className="text-ink-dim">根拠</span>: {payload.rationale}
            </p>
          )}

          {expanded && (
            <p className="mt-3 text-[10px] text-ink-faint">
              {advice.model} · {formatTs(advice.generated_at)}
            </p>
          )}

          {scheduleResult && (
            <div className="mt-3 rounded-lg bg-prog-900/20 p-3 text-xs text-prog-300">
              {scheduleResult.created.length === 0
                ? "登録対象のアクションは未来時刻にありませんでした"
                : `${scheduleResult.created.length} 件のイベントをカレンダーに登録しました`}
              {scheduleResult.created.map((ev) => (
                <div key={ev.id} className="mt-1">
                  <a
                    href={ev.htmlLink}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline hover:text-prog-300"
                  >
                    {ev.summary}
                  </a>{" "}
                  ·{" "}
                  {new Date(ev.start).toLocaleTimeString(undefined, {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              ))}
            </div>
          )}
          {scheduleError && (
            <div className="mt-3 rounded-lg bg-risk/30 p-2 text-xs text-risk">
              Calendar 登録失敗: {scheduleError}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ActionFeedback({
  fb,
  onDone,
  onRate,
}: {
  fb?: { done: boolean; rating: number };
  onDone: (done: boolean) => void;
  onRate: (rating: number) => void;
}) {
  const done = fb?.done ?? false;
  const rating = fb?.rating ?? 0;
  return (
    <div className="mt-1.5 flex basis-full items-center gap-2">
      <button
        onClick={() => onDone(!done)}
        aria-label="完了"
        className={`flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition active:scale-95 ${
          done
            ? "border-prog bg-prog-500/20 text-prog-300"
            : "border-hairline text-ink-dim hover:bg-panel"
        }`}
      >
        <Check size={12} /> {done ? "完了" : "やった"}
      </button>
      <div className="ml-auto flex items-center gap-1">
        <button
          onClick={() => onRate(rating === 1 ? 0 : 1)}
          aria-label="役に立った"
          className={`grid h-9 w-9 place-items-center rounded-full transition active:scale-90 ${
            rating === 1 ? "bg-prog-500/30 text-prog-300" : "text-ink-faint hover:text-ink-dim"
          }`}
        >
          <ThumbsUp size={13} />
        </button>
        <button
          onClick={() => onRate(rating === -1 ? 0 : -1)}
          aria-label="役に立たなかった"
          className={`grid h-9 w-9 place-items-center rounded-full transition active:scale-90 ${
            rating === -1 ? "bg-risk/30 text-risk" : "text-ink-faint hover:text-ink-dim"
          }`}
        >
          <ThumbsDown size={13} />
        </button>
      </div>
    </div>
  );
}

/** 種目デモ GIF (ExerciseDB プロキシ)。タップで表示。画像が違う時は候補から選び直せる。 */
function ExerciseGif({ name }: { name: string }) {
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const [picking, setPicking] = useState(false);
  const [candidates, setCandidates] = useState<ExerciseCandidatesResponse | null>(null);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [gifKey, setGifKey] = useState(0); // 画像確定後にキャッシュを割ってリロードさせる

  const openPicker = () => {
    setPicking((p) => !p);
    if (!candidates && !loadingCandidates) {
      setLoadingCandidates(true);
      api
        .exerciseCandidates(name)
        .then(setCandidates)
        .catch(() => setCandidates({ selected: null, candidates: [] }))
        .finally(() => setLoadingCandidates(false));
    }
  };

  const choose = async (c: ExerciseCandidate) => {
    if (!c.name) return;
    await api.exerciseOverrideSave(name, c.id, c.name);
    setCandidates((prev) =>
      prev
        ? {
            selected: { id: c.id, name: c.name, equipment: c.equipment, target: c.target, source: "override" },
            candidates: prev.candidates.map((x) => ({ ...x, selected: x.id === c.id })),
          }
        : prev,
    );
    setFailed(false);
    setOpen(true);
    setGifKey((k) => k + 1);
  };

  if (failed && !picking) {
    // デモが見つからない種目でも「候補から探す」は出す (自動一致が0件でも手動なら見つかることがある)
    return (
      <div className="basis-full mt-1">
        <button onClick={openPicker} className="text-[11px] text-ink-faint hover:text-info hover:underline">
          画像候補を探す
        </button>
      </div>
    );
  }

  return (
    <div className="basis-full mt-1">
      <div className="flex flex-wrap items-center gap-x-3">
        <button
          onClick={() => setOpen((o) => !o)}
          className="text-[11px] text-info hover:underline"
        >
          {open ? "デモを隠す" : "▶ デモを見る"}
        </button>
        {open && (
          <button onClick={openPicker} className="text-[11px] text-ink-faint hover:text-info hover:underline">
            違う画像?
          </button>
        )}
      </div>
      {open && (
        <img
          key={gifKey}
          src={`/api/exercise-gif?name=${encodeURIComponent(name)}${gifKey ? `&v=${gifKey}` : ""}`}
          alt={`${name} のデモ`}
          loading="lazy"
          onError={() => setFailed(true)}
          className="mt-1 max-h-60 w-full rounded-md border border-hairline object-contain bg-hull"
        />
      )}
      {picking && (
        <ExerciseGifPicker
          name={name}
          data={candidates}
          loading={loadingCandidates}
          onChoose={choose}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}

function ExerciseGifPicker({
  name,
  data,
  loading,
  onChoose,
  onClose,
}: {
  name: string;
  data: ExerciseCandidatesResponse | null;
  loading: boolean;
  onChoose: (c: ExerciseCandidate) => void;
  onClose: () => void;
}) {
  const [previewId, setPreviewId] = useState<string | null>(null);
  return (
    <div className="mt-2 rounded-md border border-hairline bg-hull/60 p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] text-ink-faint">画像候補 (器具限定・一致度順)</span>
        <button onClick={onClose} className="text-[10px] text-ink-faint hover:text-ink-dim">
          閉じる
        </button>
      </div>
      {loading && <p className="text-[11px] text-ink-faint">検索中…</p>}
      {!loading && data && data.candidates.length === 0 && (
        <p className="text-[11px] text-ink-faint">候補が見つかりませんでした。</p>
      )}
      <ul className="space-y-1">
        {data?.candidates.map((c) => (
          <li
            key={c.id}
            className={`rounded border px-2 py-1 ${
              c.selected ? "border-prog-300/60 bg-prog-300/10" : "border-hairline"
            }`}
          >
            <button
              className="w-full text-left"
              onClick={() => setPreviewId((p) => (p === c.id ? null : c.id))}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-ink">
                  {c.name}
                  {c.selected && <span className="ml-1 text-prog-300">(現在)</span>}
                </span>
                <span className="text-[10px] text-ink-faint">{c.equipment}</span>
              </div>
            </button>
            {previewId === c.id && (
              <div className="mt-1">
                <img
                  src={`/api/exercise-gif?name=${encodeURIComponent(name)}&id=${c.id}`}
                  alt={c.name ?? ""}
                  loading="lazy"
                  className="max-h-48 w-full rounded border border-hairline object-contain bg-hull"
                />
                {!c.selected && (
                  <button
                    onClick={() => onChoose(c)}
                    className="mt-1 rounded bg-prog-300/20 px-2 py-1 text-[11px] text-prog-300 hover:bg-prog-300/30"
                  >
                    この画像に決定
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ExerciseList({ exercises }: { exercises: NonNullable<AdviceAction["exercises"]> }) {
  return (
    <div className="basis-full mt-2 space-y-2">
      <ul className="space-y-1.5">
        {exercises.map((e, i) => (
          <li
            key={i}
            className="rounded-lg border border-panel bg-hull/50 px-3 py-2"
          >
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
              <span className="text-sm text-ink">{e.name}</span>
              {e.weight && (
                <span className="telemetry-num text-sm tabular-nums text-prog-300">
                  {e.weight}
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[11px] tabular-nums text-ink-dim">
              <span>
                <span className="text-ink-faint">セット </span>
                {e.sets}
              </span>
              <span>
                <span className="text-ink-faint">回数 </span>
                {e.reps}
              </span>
              {e.rest_sec != null && (
                <span>
                  <span className="text-ink-faint">休憩 </span>
                  {e.rest_sec}秒
                </span>
              )}
              {e.rir != null && (
                <span>
                  <span className="text-ink-faint">RIR </span>
                  {e.rir}
                </span>
              )}
              {e.tempo && (
                <span>
                  <span className="text-ink-faint">テンポ </span>
                  {e.tempo}
                </span>
              )}
            </div>
            {e.notes && (
              <div className="mt-1 text-[11px] leading-relaxed text-ink-faint">
                {e.notes}
              </div>
            )}
            <ExerciseGif name={e.name} />
          </li>
        ))}
      </ul>
      <p className="text-[10px] leading-relaxed text-ink-faint">
        <span className="text-ink-dim">RIR</span> = 限界まで何回余力を残すか (低いほど追い込む)。
        筋肥大は 1-3、筋力は 1-2、技術習得は 3-5 が目安。
        <br />
        <span className="text-ink-dim">RPE</span> = 10 段階の主観強度 (Rate of Perceived Exertion)。
        6-7 = ややきつい、8-9 = かなりきつい、10 = 限界。
      </p>
    </div>
  );
}

/** "HH:MM" → 分。パース不能は大きい値 (未来扱い)。 */
function timeToMin(hhmm: string): number {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm);
  return m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : 24 * 60;
}

/** 現在時刻 (ブラウザのローカル時刻 = ユーザーの JST) を分で返す。 */
function nowMinutes(): number {
  const d = new Date();
  return d.getHours() * 60 + d.getMinutes();
}

function formatTs(ts: string | null): string {
  if (!ts) return "--";
  return new Date(ts).toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

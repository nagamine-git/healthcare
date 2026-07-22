import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, X, Check } from "lucide-react";
import { api, type AdviceAction, type ExercisePrescription } from "../lib/api";
import { useWakeLock } from "../lib/wakeLock";

type Exercise = ExercisePrescription;

/**
 * トレーニング実行ビュー。全画面・スリープ禁止で種目を1つずつ進める。
 * 各種目: デモ GIF + 詳しいステップ (setup/execution/breathing/mistakes/tips) +
 * セット/レップ/テンポ/RIR + セット間の休憩タイマー。
 */
export function WorkoutSession({
  action,
  onClose,
}: {
  action: AdviceAction;
  onClose: () => void;
}) {
  const exercises = action.exercises ?? [];
  const [idx, setIdx] = useState(0);
  const [done, setDone] = useState(false);

  // トレ中は画面を消させない (フォームを見ながら動くため)。
  useWakeLock(!done);

  if (exercises.length === 0) {
    onClose();
    return null;
  }

  if (done) {
    return (
      <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3 bg-void px-6 text-center">
        <Check size={40} className="text-prog" strokeWidth={2.4} />
        <p className="text-[16px] font-semibold text-ink">お疲れさま。全種目 完了。</p>
        <p className="max-w-xs text-[12px] leading-relaxed text-ink-faint">
          記録は「+」から。違和感が残る種目があれば次回は重量を戻して。
        </p>
        <button
          onClick={onClose}
          className="press mt-2 rounded-control bg-prog px-6 py-2.5 text-[13px] font-semibold text-void"
        >
          終わる
        </button>
      </div>
    );
  }

  const ex = exercises[idx];
  const last = idx === exercises.length - 1;

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-void">
      {/* ヘッダ: 進捗 + 閉じる */}
      <div
        className="flex items-center justify-between px-5 pb-2"
        style={{ paddingTop: "calc(env(safe-area-inset-top) + 12px)" }}
      >
        <span className="telemetry-num text-[12px] text-ink-faint">
          {idx + 1} / {exercises.length}
        </span>
        <span className="text-[12px] font-semibold text-ink-dim">{action.title.split(" (")[0]}</span>
        <button onClick={onClose} aria-label="閉じる" className="press text-ink-faint">
          <X size={22} />
        </button>
      </div>

      {/* 種目本体 (スクロール) */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4">
        <ExerciseRunner key={idx} ex={ex} />
      </div>

      {/* フッタ: 前へ / 次へ (or 完了) */}
      <div
        className="flex items-center gap-3 border-t border-hairline px-5 pt-3"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
      >
        <button
          onClick={() => setIdx((i) => Math.max(0, i - 1))}
          disabled={idx === 0}
          className="press grid h-11 w-11 place-items-center rounded-full border border-hairline text-ink-dim disabled:opacity-30"
          aria-label="前の種目"
        >
          <ChevronLeft size={20} />
        </button>
        <button
          onClick={() => (last ? setDone(true) : setIdx((i) => i + 1))}
          className="press flex h-11 flex-1 items-center justify-center gap-1 rounded-full bg-prog text-[14px] font-semibold text-void"
        >
          {last ? "完了" : "次の種目"}
          {!last && <ChevronRight size={18} />}
        </button>
      </div>
    </div>
  );
}

/** 1 種目の実行画面: 見出し・処方・GIF・休憩タイマー・詳しいステップ。 */
function ExerciseRunner({ ex }: { ex: Exercise }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <h2 className="text-[18px] font-semibold text-ink">{ex.name}</h2>
        {ex.weight && (
          <span className="telemetry-num text-[16px] font-semibold text-prog-300">{ex.weight}</span>
        )}
      </div>

      {/* 処方チップ */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[12px] tabular-nums text-ink-dim">
        <Chip label="セット" value={`${ex.sets}`} />
        <Chip label="回数" value={ex.reps} />
        {ex.rir != null && <Chip label="RIR" value={`${ex.rir}`} />}
        {ex.tempo && <Chip label="テンポ" value={ex.tempo} />}
      </div>

      <GifBlock name={ex.name} />

      {ex.rest_sec != null && <RestTimer seconds={ex.rest_sec} />}

      {ex.notes && (
        <p className="rounded-lg bg-hull/50 px-3 py-2 text-[12px] leading-relaxed text-ink-faint">
          {ex.notes}
        </p>
      )}

      <GuideBlock name={ex.name} />
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <span className="text-ink-faint">{label} </span>
      {value}
    </span>
  );
}

/** デモ GIF (実行ビューでは常時表示)。無ければ静かに畳む。 */
function GifBlock({ name }: { name: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <div className="overflow-hidden rounded-xl border border-hairline bg-white">
      <img
        src={`/api/exercise-gif?name=${encodeURIComponent(name)}`}
        alt={`${name} のデモ`}
        className="mx-auto max-h-72 w-full object-contain"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

/** セット間の休憩タイマー。押すと開始、0 で通知色に。 */
function RestTimer({ seconds }: { seconds: number }) {
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    if (left == null) return;
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((v) => (v == null ? null : v - 1)), 1000);
    return () => clearTimeout(t);
  }, [left]);

  const running = left != null && left > 0;
  const finished = left === 0;
  const mm = Math.floor((left ?? seconds) / 60);
  const ss = String((left ?? seconds) % 60).padStart(2, "0");

  return (
    <button
      onClick={() => setLeft(seconds)}
      className={`press flex w-full items-center justify-between rounded-control px-4 py-2.5 text-[13px] font-semibold ${
        finished
          ? "bg-prog/15 text-prog"
          : running
            ? "bg-act/15 text-act"
            : "border border-hairline text-ink-dim"
      }`}
    >
      <span>{finished ? "休憩おわり — 次のセットへ" : running ? "休憩中" : "休憩をはじめる"}</span>
      <span className="telemetry-num tabular-nums">
        {mm}:{ss}
      </span>
    </button>
  );
}

/** 詳しいステップ (LLM 生成 + キャッシュ)。未生成ならタップで生成。 */
function GuideBlock({ name }: { name: string }) {
  const [generate, setGenerate] = useState(false);
  const cached = useQuery({
    queryKey: ["exercise-guide", name],
    queryFn: () => api.exerciseGuide(name),
    staleTime: 60 * 60 * 1000,
  });
  const gen = useQuery({
    queryKey: ["exercise-guide-gen", name],
    queryFn: () => api.exerciseGuideGenerate(name),
    enabled: generate,
    staleTime: 60 * 60 * 1000,
  });

  const guide = gen.data?.steps ?? cached.data?.steps;
  const hasGuide = guide && Object.values(guide).some((a) => a && a.length > 0);
  const loading = cached.isLoading || (generate && gen.isLoading);

  if (!hasGuide) {
    return (
      <button
        onClick={() => setGenerate(true)}
        disabled={loading}
        className="press w-full rounded-control border border-hairline py-2.5 text-[13px] font-medium text-info disabled:opacity-50"
      >
        {loading ? "詳しいフォームを生成中…" : "詳しいフォームを見る"}
      </button>
    );
  }

  return (
    <div className="space-y-3">
      <GuideSection title="準備" items={guide!.setup} accent="text-ink-dim" />
      <GuideSection title="動作" items={guide!.execution} accent="text-ink" />
      <GuideSection title="呼吸" items={guide!.breathing} accent="text-info" />
      <GuideSection title="よくあるミス" items={guide!.mistakes} accent="text-risk" />
      <GuideSection title="コツ" items={guide!.tips} accent="text-prog" />
    </div>
  );
}

function GuideSection({
  title,
  items,
  accent,
}: {
  title: string;
  items?: string[];
  accent: string;
}) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <div className="telemetry-label mb-1">{title}</div>
      <ul className="space-y-1">
        {items.map((s, i) => (
          <li key={i} className="flex gap-2 text-[12.5px] leading-relaxed text-ink-dim">
            <span className={`mt-1.5 h-1 w-1 shrink-0 rounded-full ${accent} bg-current`} />
            <span className="min-w-0 flex-1">{s}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

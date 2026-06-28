import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ChevronDown, History, Info, Pencil, Timer, TimerReset, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, type FitnessComposite, type FitnessTestEntry } from "../lib/api";
import { BellCurve } from "./BellCurve";
import { MeasureModal } from "./measure/MeasureModal";

const TEST_LABEL: Record<string, string> = {
  grip: "握力",
  push_up: "腕立て",
  chair_stand: "椅子立ち",
  srt: "SRT",
};

/** 総合体力スコア (0-100) + 内訳バー。医学エビデンス重み付けの加重平均。 */
function CompositeScoreBanner({ composite }: { composite: FitnessComposite }) {
  return (
    <div className="rounded-xl bg-void/40 p-3 ring-1 ring-panel/60">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-ink">総合体力スコア</span>
        <span className="text-2xl font-bold tabular-nums text-sky-300">
          {Math.round(composite.score)}
          <span className="ml-0.5 text-xs font-normal text-ink-dim">/100</span>
        </span>
      </div>
      <div className="mt-1 text-[10px] text-ink-faint">
        同年代・同性比の percentile を予後エビデンスで重み付け平均 ({composite.n_tests}種測定済み)
      </div>
      <div className="mt-2 space-y-1">
        {composite.contributions.map((c) => (
          <div key={c.key} className="flex items-center gap-2">
            <span className="w-14 shrink-0 text-[10px] text-ink-dim">{TEST_LABEL[c.key] ?? c.key}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-panel">
              <div
                className="h-full rounded-full bg-sky-500/70"
                style={{ width: `${Math.max(2, Math.min(100, c.percentile))}%` }}
              />
            </div>
            <span className="w-8 shrink-0 text-right text-[10px] tabular-nums text-ink-dim">
              {Math.round(c.percentile)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * 自宅フィットネスチェック。医学的に予後と相関する4テスト (腕立て/握力/
 * 椅子立ち上がり/座って立つ) を記録し、基準値バンド・前回比 (MDC で実変化判定)・
 * テストごとの再測定推奨を表示する。
 * 設計: docs/superpowers/specs/2026-06-22-home-fitness-test-design.md
 */
export function FitnessTestPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["fitness-tests"], queryFn: api.fitnessTests });
  const record = useMutation({
    mutationFn: api.fitnessRecord,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["fitness-tests"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const data = q.data;
  if (!data) return null;

  return (
    <section className="space-y-3 rounded-xl bg-gradient-to-b from-hull/80 to-hull/40 p-4 sm:p-5 ring-1 ring-panel">
      <div className="flex items-center gap-2">
        <Activity size={16} className="text-sky-300" />
        <h3 className="text-sm tracking-wide text-ink">自宅フィットネスチェック</h3>
      </div>
      <p className="text-[11px] leading-relaxed text-ink-faint">
        体型 (形) では見えない機能的フィットネスを測る。器具最小限・短時間で、
        予後と相関が裏付けられた4テスト。力む局面では息を吐く (片頭痛の労作性誘因を避ける)。
      </p>
      {!data.evaluable && (
        <div className="flex items-start gap-1.5 rounded-lg bg-void/40 px-3 py-2 text-[11px] text-ink-dim">
          <Info size={13} className="mt-0.5 shrink-0 text-ink-faint" />
          設定で生年月日・性別を入れると、絶対値に加えて基準値評価 (優/良/平均/要改善) が出ます。
        </div>
      )}

      {data.composite && <CompositeScoreBanner composite={data.composite} />}

      <div className="space-y-2.5">
        {data.tests.map((t) => (
          <TestCard
            key={t.definition.key}
            entry={t}
            saving={record.isPending}
            onRecord={(body) => record.mutate(body)}
          />
        ))}
      </div>
    </section>
  );
}

/**
 * サマリー用の軽量バナー。再測定 due のテストがあるときだけ表示する。
 * FitnessTestPanel と同じクエリキーを使うので追加フェッチは発生しない。
 */
export function FitnessDueBanner({ onOpen }: { onOpen?: () => void }) {
  const q = useQuery({ queryKey: ["fitness-tests"], queryFn: api.fitnessTests });
  const data = q.data;
  if (!data || !data.any_due || data.due_labels.length === 0) return null;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-2 rounded-xl bg-act/10 px-3 py-2 text-left text-[11px] text-act-300 ring-1 ring-act/30 hover:bg-act/15"
    >
      <TimerReset size={13} className="shrink-0 text-act-300" />
      <span className="min-w-0 flex-1">
        フィットネスチェック: {data.due_labels.join("・")} が測り時
      </span>
      <ChevronDown size={14} className="-rotate-90 shrink-0 text-act-300/70" />
    </button>
  );
}

const BAND_COLOR: Record<string, string> = {
  excellent: "bg-prog-500/15 text-prog-300 ring-prog/30",
  good: "bg-sky-500/15 text-sky-300 ring-sky-600/30",
  average: "bg-ink-faint/15 text-ink-dim ring-ink-faint/30",
  needs_work: "bg-act/15 text-act-300 ring-act/30",
  alert: "bg-risk/15 text-risk ring-risk/30",
};

function TestCard({
  entry,
  saving,
  onRecord,
}: {
  entry: FitnessTestEntry;
  saving: boolean;
  onRecord: (body: { test_key: string; value?: number; left?: number; right?: number }) => void;
}) {
  const { definition: d, latest, evaluation, trend, due } = entry;
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [measuring, setMeasuring] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const submit = () => {
    if (d.has_lr) {
      const l = parseFloat(left);
      const r = parseFloat(right);
      if (Number.isNaN(l) && Number.isNaN(r)) return;
      onRecord({
        test_key: d.key,
        ...(Number.isNaN(l) ? {} : { left: l }),
        ...(Number.isNaN(r) ? {} : { right: r }),
      });
      setLeft("");
      setRight("");
    } else {
      const v = parseFloat(value);
      if (Number.isNaN(v)) return;
      onRecord({ test_key: d.key, value: v });
      setValue("");
    }
  };

  return (
    <div className="rounded-xl bg-void/40 ring-1 ring-panel/60">
      <div className="flex items-start gap-2 p-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink">{d.label}</span>
            {evaluation && (
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] ring-1 ${
                  BAND_COLOR[evaluation.status] ?? BAND_COLOR.average
                }`}
              >
                {evaluation.label}
              </span>
            )}
            {due.is_due && (
              <span className="flex items-center gap-1 rounded-full bg-act/10 px-2 py-0.5 text-[10px] text-act-300 ring-1 ring-act/30">
                <TimerReset size={10} /> 測り時
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[11px] text-ink-faint">{d.target}</div>

          {/* 最新値 + 前回比 */}
          <div className="mt-1.5 flex items-baseline gap-2">
            {latest ? (
              <>
                <span className="text-lg font-semibold tabular-nums text-ink">
                  {latest.value}
                  <span className="ml-0.5 text-xs font-normal text-ink-dim">{d.unit}</span>
                </span>
                {trend && (
                  <span
                    className={`text-[11px] tabular-nums ${
                      trend.improved == null
                        ? "text-ink-faint"
                        : trend.improved
                          ? "text-prog-300"
                          : "text-risk"
                    }`}
                  >
                    {trend.delta > 0 ? "+" : ""}
                    {trend.delta}
                    {d.unit}{" "}
                    <span className="text-ink-faint">
                      {trend.is_real_change ? "(実変化)" : "(誤差範囲)"}
                    </span>
                  </span>
                )}
              </>
            ) : (
              <span className="text-[11px] text-ink-faint">未測定</span>
            )}
          </div>
          <div className="mt-0.5 text-[10px] text-ink-faint">
            {d.reference}
            {due.due_on && !due.is_due && ` ・次回推奨 ${due.due_on}`}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="shrink-0 rounded-lg p-1 text-ink-faint hover:text-ink-dim"
          aria-label="手順を表示"
        >
          <ChevronDown size={16} className={open ? "rotate-180 transition" : "transition"} />
        </button>
      </div>

      {/* 母集団分布 (連続値テストのみ) */}
      {entry.distribution && latest && (
        <div className="border-t border-panel/60 px-3 pb-2 pt-1">
          <BellCurve
            idKey={d.key}
            value={latest.value}
            mean={entry.distribution.mean}
            sd={entry.distribution.sd}
          />
          <div className="mt-0.5 text-[11px] text-ink-dim">
            同年代・同性で{" "}
            <span className="font-semibold tabular-nums text-sky-300">
              {Math.round(entry.distribution.percentile)}
            </span>
            <span className="text-ink-faint"> パーセンタイル</span>
          </div>
        </div>
      )}

      {/* 手順 (折りたたみ) */}
      {open && (
        <div className="space-y-1.5 border-t border-panel/60 px-3 py-2.5 text-[11px] leading-relaxed text-ink-dim">
          {d.steps && d.steps.length > 0 ? (
            <div>
              <div className="text-ink-faint">手順:</div>
              <ol className="mt-1 list-decimal space-y-1 pl-4 marker:text-ink-faint">
                {d.steps.map((s, i) => (
                  <li key={i} className="pl-0.5">{s}</li>
                ))}
              </ol>
            </div>
          ) : (
            <p><span className="text-ink-faint">手順:</span> {d.protocol}</p>
          )}
          <p><span className="text-ink-faint">器具:</span> {d.equipment}・約{d.est_minutes}分</p>
          <p><span className="text-ink-faint">ウォームアップ:</span> {d.warmup}</p>
          <p className="text-act-300/70">⚠ {d.migraine_note}</p>
          <p className="text-ink-faint">再測定の目安: {d.retest_weeks}週ごと</p>
        </div>
      )}

      {/* 記録入力 */}
      <div className="flex items-center gap-2 border-t border-panel/60 px-3 py-2">
        {d.has_lr ? (
          <>
            <NumInput placeholder="左" value={left} onChange={setLeft} unit={d.unit} />
            <NumInput placeholder="右" value={right} onChange={setRight} unit={d.unit} />
          </>
        ) : (
          <NumInput placeholder="記録" value={value} onChange={setValue} unit={d.unit} />
        )}
        {d.measure_mode && (
          <button
            type="button"
            onClick={() => setMeasuring(true)}
            className="flex shrink-0 items-center gap-1 rounded-lg bg-panel px-3 py-1.5 text-xs font-medium text-sky-300 hover:bg-hairline"
          >
            <Timer size={13} /> 測定
          </button>
        )}
        <button
          type="button"
          disabled={saving}
          onClick={submit}
          className="ml-auto shrink-0 rounded-lg bg-sky-600/80 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-600 disabled:opacity-50"
        >
          記録
        </button>
      </div>

      {/* 履歴 (閲覧・編集・削除) */}
      <div className="border-t border-panel/60 px-3 py-1.5">
        <button
          type="button"
          onClick={() => setShowHistory((s) => !s)}
          className="flex items-center gap-1.5 text-[11px] text-ink-faint hover:text-ink-dim"
        >
          <History size={12} />
          履歴
          <ChevronDown size={13} className={showHistory ? "rotate-180 transition" : "transition"} />
        </button>
      </div>
      {showHistory && <HistorySection testKey={d.key} unit={d.unit} editable={!d.has_lr} />}

      {measuring && d.measure_mode && (
        <MeasureModal
          mode={d.measure_mode}
          label={d.label}
          onFinish={(n) => {
            setValue(String(n));
            setMeasuring(false);
          }}
          onClose={() => setMeasuring(false)}
        />
      )}
    </div>
  );
}

/**
 * 1テストの過去記録一覧。各行を編集 (UPSERT で同日上書き) / 削除できる。
 * 握力など左右別 (editable=false) は値の構造が違うため編集は出さず削除のみ。
 */
function HistorySection({
  testKey,
  unit,
  editable,
}: {
  testKey: string;
  unit: string;
  editable: boolean;
}) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["fitness-history", testKey],
    queryFn: () => api.fitnessHistory(testKey),
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["fitness-history", testKey] });
    qc.invalidateQueries({ queryKey: ["fitness-tests"] });
    qc.invalidateQueries({ queryKey: ["today"] });
  };
  const edit = useMutation({ mutationFn: api.fitnessRecord, onSuccess: invalidate });
  const del = useMutation({ mutationFn: api.fitnessDelete, onSuccess: invalidate });

  const [editId, setEditId] = useState<number | null>(null);
  const [editVal, setEditVal] = useState("");

  const items = q.data?.items ?? [];
  if (q.isLoading) return <div className="px-3 py-2 text-[11px] text-ink-faint">読み込み中…</div>;
  if (items.length === 0)
    return <div className="px-3 py-2 text-[11px] text-ink-faint">まだ記録がありません。</div>;

  return (
    <ul className="divide-y divide-panel/40 px-3 pb-2">
      {items.map((it) => {
        const isEditing = editId === it.id;
        return (
          <li key={it.id} className="flex items-center gap-2 py-1.5 text-[12px]">
            <span className="w-20 shrink-0 tabular-nums text-ink-faint">{it.performed_on}</span>
            {isEditing ? (
              <>
                <input
                  type="number"
                  inputMode="decimal"
                  value={editVal}
                  onChange={(e) => setEditVal(e.target.value)}
                  className="w-20 rounded bg-hull/60 px-2 py-1 tabular-nums text-ink outline-none ring-1 ring-hairline"
                />
                <button
                  type="button"
                  disabled={edit.isPending}
                  onClick={() => {
                    const v = parseFloat(editVal);
                    if (Number.isNaN(v)) return;
                    edit.mutate({ test_key: testKey, value: v, performed_on: it.performed_on });
                    setEditId(null);
                  }}
                  className="rounded bg-sky-600/80 px-2 py-1 text-[11px] text-white hover:bg-sky-600 disabled:opacity-50"
                >
                  保存
                </button>
                <button
                  type="button"
                  onClick={() => setEditId(null)}
                  className="px-1 text-[11px] text-ink-faint hover:text-ink-dim"
                >
                  取消
                </button>
              </>
            ) : (
              <>
                <span className="flex-1 tabular-nums text-ink">
                  {it.value}
                  <span className="ml-0.5 text-[10px] text-ink-faint">{unit}</span>
                  {it.detail && (it.detail.left != null || it.detail.right != null) && (
                    <span className="ml-1.5 text-[10px] text-ink-faint">
                      (左{it.detail.left ?? "-"}/右{it.detail.right ?? "-"})
                    </span>
                  )}
                </span>
                {editable && (
                  <button
                    type="button"
                    onClick={() => {
                      setEditId(it.id);
                      setEditVal(String(it.value));
                    }}
                    className="rounded p-1 text-ink-faint hover:text-sky-300"
                    aria-label="編集"
                  >
                    <Pencil size={13} />
                  </button>
                )}
                <button
                  type="button"
                  disabled={del.isPending}
                  onClick={() => {
                    if (window.confirm(`${it.performed_on} の記録を削除しますか?`)) del.mutate(it.id);
                  }}
                  className="rounded p-1 text-ink-faint hover:text-risk disabled:opacity-50"
                  aria-label="削除"
                >
                  <Trash2 size={13} />
                </button>
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function NumInput({
  placeholder,
  value,
  onChange,
  unit,
}: {
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  unit: string;
}) {
  return (
    <div className="flex items-center gap-1 rounded-lg bg-hull/60 px-2 py-1 ring-1 ring-panel">
      <input
        type="number"
        inputMode="decimal"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-16 bg-transparent text-sm tabular-nums text-ink outline-none placeholder:text-ink-faint"
      />
      <span className="text-[10px] text-ink-faint">{unit}</span>
    </div>
  );
}

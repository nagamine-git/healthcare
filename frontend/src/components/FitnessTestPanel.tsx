import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ChevronDown, History, Info, Pencil, Timer, TimerReset, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, type FitnessTestEntry } from "../lib/api";
import { MeasureModal } from "./measure/MeasureModal";

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
    <section className="space-y-3 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 p-4 sm:p-5 ring-1 ring-slate-800">
      <div className="flex items-center gap-2">
        <Activity size={16} className="text-sky-300" />
        <h3 className="text-sm tracking-wide text-slate-100">自宅フィットネスチェック</h3>
      </div>
      <p className="text-[11px] leading-relaxed text-slate-500">
        体型 (形) では見えない機能的フィットネスを測る。器具最小限・短時間で、
        予後と相関が裏付けられた4テスト。力む局面では息を吐く (片頭痛の労作性誘因を避ける)。
      </p>
      {!data.evaluable && (
        <div className="flex items-start gap-1.5 rounded-lg bg-slate-950/40 px-3 py-2 text-[11px] text-slate-400">
          <Info size={13} className="mt-0.5 shrink-0 text-slate-500" />
          設定で生年月日・性別を入れると、絶対値に加えて基準値評価 (優/良/平均/要改善) が出ます。
        </div>
      )}

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
      className="flex w-full items-center gap-2 rounded-xl bg-amber-500/10 px-3 py-2 text-left text-[11px] text-amber-200 ring-1 ring-amber-600/30 hover:bg-amber-500/15"
    >
      <TimerReset size={13} className="shrink-0 text-amber-300" />
      <span className="min-w-0 flex-1">
        フィットネスチェック: {data.due_labels.join("・")} が測り時
      </span>
      <ChevronDown size={14} className="-rotate-90 shrink-0 text-amber-300/70" />
    </button>
  );
}

const BAND_COLOR: Record<string, string> = {
  excellent: "bg-emerald-500/15 text-emerald-300 ring-emerald-600/30",
  good: "bg-sky-500/15 text-sky-300 ring-sky-600/30",
  average: "bg-slate-500/15 text-slate-300 ring-slate-600/30",
  needs_work: "bg-amber-500/15 text-amber-300 ring-amber-600/30",
  alert: "bg-rose-500/15 text-rose-300 ring-rose-600/30",
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
    <div className="rounded-xl bg-slate-950/40 ring-1 ring-slate-800/60">
      <div className="flex items-start gap-2 p-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-100">{d.label}</span>
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
              <span className="flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300 ring-1 ring-amber-600/30">
                <TimerReset size={10} /> 測り時
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[11px] text-slate-500">{d.target}</div>

          {/* 最新値 + 前回比 */}
          <div className="mt-1.5 flex items-baseline gap-2">
            {latest ? (
              <>
                <span className="text-lg font-semibold tabular-nums text-slate-100">
                  {latest.value}
                  <span className="ml-0.5 text-xs font-normal text-slate-400">{d.unit}</span>
                </span>
                {trend && (
                  <span
                    className={`text-[11px] tabular-nums ${
                      trend.improved == null
                        ? "text-slate-500"
                        : trend.improved
                          ? "text-emerald-400"
                          : "text-rose-400"
                    }`}
                  >
                    {trend.delta > 0 ? "+" : ""}
                    {trend.delta}
                    {d.unit}{" "}
                    <span className="text-slate-500">
                      {trend.is_real_change ? "(実変化)" : "(誤差範囲)"}
                    </span>
                  </span>
                )}
              </>
            ) : (
              <span className="text-[11px] text-slate-500">未測定</span>
            )}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-600">
            {d.reference}
            {due.due_on && !due.is_due && ` ・次回推奨 ${due.due_on}`}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="shrink-0 rounded-lg p-1 text-slate-500 hover:text-slate-300"
          aria-label="手順を表示"
        >
          <ChevronDown size={16} className={open ? "rotate-180 transition" : "transition"} />
        </button>
      </div>

      {/* 手順 (折りたたみ) */}
      {open && (
        <div className="space-y-1.5 border-t border-slate-800/60 px-3 py-2.5 text-[11px] leading-relaxed text-slate-400">
          {d.steps && d.steps.length > 0 ? (
            <div>
              <div className="text-slate-500">手順:</div>
              <ol className="mt-1 list-decimal space-y-1 pl-4 marker:text-slate-600">
                {d.steps.map((s, i) => (
                  <li key={i} className="pl-0.5">{s}</li>
                ))}
              </ol>
            </div>
          ) : (
            <p><span className="text-slate-500">手順:</span> {d.protocol}</p>
          )}
          <p><span className="text-slate-500">器具:</span> {d.equipment}・約{d.est_minutes}分</p>
          <p><span className="text-slate-500">ウォームアップ:</span> {d.warmup}</p>
          <p className="text-amber-300/70">⚠ {d.migraine_note}</p>
          <p className="text-slate-600">再測定の目安: {d.retest_weeks}週ごと</p>
        </div>
      )}

      {/* 記録入力 */}
      <div className="flex items-center gap-2 border-t border-slate-800/60 px-3 py-2">
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
            className="flex shrink-0 items-center gap-1 rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-sky-300 hover:bg-slate-700"
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
      <div className="border-t border-slate-800/60 px-3 py-1.5">
        <button
          type="button"
          onClick={() => setShowHistory((s) => !s)}
          className="flex items-center gap-1.5 text-[11px] text-slate-500 hover:text-slate-300"
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
  if (q.isLoading) return <div className="px-3 py-2 text-[11px] text-slate-500">読み込み中…</div>;
  if (items.length === 0)
    return <div className="px-3 py-2 text-[11px] text-slate-600">まだ記録がありません。</div>;

  return (
    <ul className="divide-y divide-slate-800/40 px-3 pb-2">
      {items.map((it) => {
        const isEditing = editId === it.id;
        return (
          <li key={it.id} className="flex items-center gap-2 py-1.5 text-[12px]">
            <span className="w-20 shrink-0 tabular-nums text-slate-500">{it.performed_on}</span>
            {isEditing ? (
              <>
                <input
                  type="number"
                  inputMode="decimal"
                  value={editVal}
                  onChange={(e) => setEditVal(e.target.value)}
                  className="w-20 rounded bg-slate-900/60 px-2 py-1 tabular-nums text-slate-100 outline-none ring-1 ring-slate-700"
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
                  className="px-1 text-[11px] text-slate-500 hover:text-slate-300"
                >
                  取消
                </button>
              </>
            ) : (
              <>
                <span className="flex-1 tabular-nums text-slate-100">
                  {it.value}
                  <span className="ml-0.5 text-[10px] text-slate-500">{unit}</span>
                  {it.detail && (it.detail.left != null || it.detail.right != null) && (
                    <span className="ml-1.5 text-[10px] text-slate-500">
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
                    className="rounded p-1 text-slate-500 hover:text-sky-300"
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
                  className="rounded p-1 text-slate-500 hover:text-rose-400 disabled:opacity-50"
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
    <div className="flex items-center gap-1 rounded-lg bg-slate-900/60 px-2 py-1 ring-1 ring-slate-800">
      <input
        type="number"
        inputMode="decimal"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-16 bg-transparent text-sm tabular-nums text-slate-100 outline-none placeholder:text-slate-600"
      />
      <span className="text-[10px] text-slate-500">{unit}</span>
    </div>
  );
}

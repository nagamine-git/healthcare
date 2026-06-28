import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { MigraineEpisode } from "../lib/api";
import { localToJstIso } from "../lib/datetime";

export function MigrainePanel() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["migraine-list"],
    queryFn: () => api.migraineList(30),
    refetchInterval: 60_000,
  });

  const start = useMutation({
    mutationFn: ({ severity, tsIso }: { severity?: number; tsIso?: string }) =>
      api.migraineStart({ severity, ts_iso: tsIso }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["migraine-list"] }),
  });
  const end = useMutation({
    mutationFn: ({ tsIso }: { tsIso?: string } = {}) =>
      api.migraineEnd({ ts_iso: tsIso }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["migraine-list"] }),
  });
  const del = useMutation({
    mutationFn: (id: number) => api.migraineDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["migraine-list"] }),
  });
  const patch = useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number;
      started_at_iso?: string;
      ended_at_iso?: string;
      severity?: number;
      note?: string;
      clear_ended_at?: boolean;
    }) => api.migrainePatch(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["migraine-list"] }),
  });

  const [severity, setSeverity] = useState(5);
  const [editingId, setEditingId] = useState<number | null>(null);

  const active = list.data?.active ?? null;

  return (
    <div className="rounded-xl bg-hull/70 p-4 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-ink-dim">偏頭痛トラッカー</h3>
        {list.data && (
          <span className="text-[10px] text-ink-faint">
            直近 30 日: {list.data.count_30d} 回
          </span>
        )}
      </div>

      {/* 環境情報 (気圧 / 大気質 / 朝の光) は EnvironmentPanel に集約 */}

      {active ? (
        <ActiveBlock
          episode={active}
          onEnd={(tsLocal) => end.mutate({ tsIso: localToJstIso(tsLocal) })}
          pending={end.isPending}
        />
      ) : (
        <IdleBlock
          severity={severity}
          onSeverityChange={setSeverity}
          onStart={(tsLocal) =>
            start.mutate({ severity, tsIso: localToJstIso(tsLocal) })
          }
          pending={start.isPending}
        />
      )}

      {list.data && list.data.items.length > 0 && (
        <HistoryList
          items={list.data.items}
          onDelete={(id) => del.mutate(id)}
          deletingId={del.variables ?? null}
          onEdit={(id) => setEditingId(id)}
        />
      )}

      {editingId != null && list.data && (
        <EditModal
          item={list.data.items.find((i) => i.id === editingId) ?? null}
          onClose={() => setEditingId(null)}
          onSave={(body) => {
            patch.mutate({ id: editingId, ...body });
            setEditingId(null);
          }}
        />
      )}
    </div>
  );
}


function ActiveBlock({
  episode,
  onEnd,
  pending,
}: {
  episode: MigraineEpisode;
  onEnd: (tsLocal: string) => void;
  pending: boolean;
}) {
  // 経過時間を分単位で 1 分ごとに更新
  const [now, setNow] = useState(() => Date.now());
  const [endTs, setEndTs] = useState("");
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);
  const elapsedMin = Math.max(
    0,
    Math.floor((now - new Date(episode.started_at).getTime()) / 60_000),
  );
  const hh = Math.floor(elapsedMin / 60);
  const mm = elapsedMin % 60;

  return (
    <div className="rounded-xl border border-risk/60 bg-risk/20 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-wider text-risk">
            進行中
          </div>
          <div className="mt-1 telemetry-num text-2xl tabular-nums text-risk">
            {hh}h {mm.toString().padStart(2, "0")}m 経過
          </div>
          <div className="mt-0.5 text-xs text-risk/70">
            開始 {episode.started_at_jst}
            {episode.severity != null && ` · 強度 ${episode.severity}/10`}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <label className="flex items-center gap-1 text-[10px] text-risk/70">
            終了時刻
            <input
              type="datetime-local"
              value={endTs}
              onChange={(e) => setEndTs(e.target.value)}
              className="rounded border border-risk/40 bg-risk/40 px-1.5 py-0.5 text-[10px] text-risk focus:border-prog focus:outline-none"
            />
            {endTs && (
              <button
                type="button"
                onClick={() => setEndTs("")}
                className="text-risk/60 hover:text-risk"
                title="クリアして今に戻す"
              >
                ×
              </button>
            )}
          </label>
          <button
            onClick={() => onEnd(endTs)}
            disabled={pending}
            className="rounded-full border border-prog-700/60 bg-prog-900/30 px-4 py-2 text-sm text-prog-300 hover:bg-prog-900/60 disabled:opacity-50"
          >
            {pending ? "..." : "治った"}
          </button>
        </div>
      </div>
    </div>
  );
}

function IdleBlock({
  severity,
  onSeverityChange,
  onStart,
  pending,
}: {
  severity: number;
  onSeverityChange: (n: number) => void;
  onStart: (tsLocal: string) => void;
  pending: boolean;
}) {
  const [startTs, setStartTs] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        onClick={() => onStart(startTs)}
        disabled={pending}
        className="rounded-full border border-risk/70 bg-risk/30 px-5 py-3 text-base text-risk hover:bg-risk/60 disabled:opacity-50"
      >
        {pending ? "..." : "痛くなった"}
      </button>
      <label className="flex items-center gap-2 text-xs text-ink-dim">
        強度
        <input
          type="range"
          min={1}
          max={10}
          value={severity}
          onChange={(e) => onSeverityChange(parseInt(e.target.value, 10))}
          className="accent-risk"
        />
        <span className="w-6 text-right telemetry-num tabular-nums text-ink">
          {severity}
        </span>
      </label>
      <label className="ml-auto flex items-center gap-1 text-[10px] text-ink-faint">
        開始時刻
        <input
          type="datetime-local"
          value={startTs}
          onChange={(e) => setStartTs(e.target.value)}
          className="rounded border border-hairline bg-hull px-1.5 py-0.5 text-[10px] text-ink-dim focus:border-risk focus:outline-none"
        />
        {startTs ? (
          <button
            type="button"
            onClick={() => setStartTs("")}
            className="text-ink-faint hover:text-ink-dim"
            title="クリアして今に戻す"
          >
            ×
          </button>
        ) : (
          <span className="text-ink-faint">空=今</span>
        )}
      </label>
    </div>
  );
}

function HistoryList({
  items,
  onDelete,
  deletingId,
  onEdit,
}: {
  items: MigraineEpisode[];
  onDelete: (id: number) => void;
  deletingId: number | null;
  onEdit: (id: number) => void;
}) {
  return (
    <div className="mt-4 rounded-xl border border-panel bg-hull/40 p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wider text-ink-faint">
        履歴 (直近 30 日)
      </div>
      <ul className="space-y-1">
        {items
          .filter((i) => !i.active)
          .slice(0, 10)
          .map((it) => (
            <li key={it.id} className="flex items-baseline gap-2 text-xs">
              <span className="telemetry-num tabular-nums text-ink-dim">
                {it.started_at_jst}
              </span>
              {it.duration_min != null && (
                <span className="text-ink-faint">
                  → {formatDuration(it.duration_min)}
                </span>
              )}
              {it.severity != null && (
                <span className="rounded border border-risk/40 px-1 text-[10px] text-risk">
                  {it.severity}/10
                </span>
              )}
              {it.note && (
                <span className="truncate text-ink-faint" title={it.note}>
                  · {it.note}
                </span>
              )}
              <button
                onClick={() => onEdit(it.id)}
                className="ml-auto text-ink-faint hover:text-act-300"
                title="編集"
              >
                ✎
              </button>
              <button
                onClick={() => onDelete(it.id)}
                disabled={deletingId === it.id}
                className="text-ink-faint hover:text-risk disabled:opacity-30"
                title="削除"
              >
                ×
              </button>
            </li>
          ))}
      </ul>
    </div>
  );
}

function EditModal({
  item,
  onClose,
  onSave,
}: {
  item: MigraineEpisode | null;
  onClose: () => void;
  onSave: (body: {
    started_at_iso?: string;
    ended_at_iso?: string;
    severity?: number;
    note?: string;
    clear_ended_at?: boolean;
  }) => void;
}) {
  const toLocal = (iso: string | null) =>
    iso
      ? new Date(iso)
          .toLocaleString("sv-SE", { timeZone: "Asia/Tokyo" })
          .slice(0, 16)
          .replace(" ", "T")
      : "";

  const initialStart = item ? toLocal(item.started_at) : "";
  const initialEnd = item ? toLocal(item.ended_at) : "";

  const [startTs, setStartTs] = useState(initialStart);
  const [endTs, setEndTs] = useState(initialEnd);
  const [severity, setSeverity] = useState(item?.severity ?? 5);
  const [note, setNote] = useState(item?.note ?? "");

  if (!item) return null;

  const handleSave = () => {
    const body: {
      started_at_iso?: string;
      ended_at_iso?: string;
      severity?: number;
      note?: string;
      clear_ended_at?: boolean;
    } = {};
    if (startTs && startTs !== initialStart) {
      body.started_at_iso = localToJstIso(startTs);
    }
    if (endTs !== initialEnd) {
      if (endTs === "" && item.ended_at) {
        body.clear_ended_at = true;
      } else if (endTs) {
        body.ended_at_iso = localToJstIso(endTs);
      }
    }
    if (severity !== item.severity) body.severity = severity;
    if (note !== (item.note ?? "")) body.note = note;
    onSave(body);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-hairline bg-hull p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 text-sm tracking-wider text-ink-dim">
          偏頭痛エピソードの編集
        </div>
        <div className="space-y-3 text-xs">
          <label className="flex items-center justify-between gap-3">
            <span className="text-ink-dim">開始</span>
            <input
              type="datetime-local"
              value={startTs}
              onChange={(e) => setStartTs(e.target.value)}
              className="flex-1 rounded border border-hairline bg-panel px-2 py-1 text-ink"
            />
          </label>
          <label className="flex items-center justify-between gap-3">
            <span className="text-ink-dim">終了</span>
            <input
              type="datetime-local"
              value={endTs}
              onChange={(e) => setEndTs(e.target.value)}
              className="flex-1 rounded border border-hairline bg-panel px-2 py-1 text-ink"
            />
            {endTs && (
              <button
                type="button"
                onClick={() => setEndTs("")}
                className="text-ink-faint hover:text-risk"
                title="クリア (再 active 化)"
              >
                ×
              </button>
            )}
          </label>
          <label className="flex items-center justify-between gap-3">
            <span className="text-ink-dim">強度</span>
            <input
              type="range"
              min={1}
              max={10}
              value={severity}
              onChange={(e) => setSeverity(parseInt(e.target.value, 10))}
              className="flex-1 accent-risk"
            />
            <span className="w-6 text-right telemetry-num tabular-nums text-ink">
              {severity}
            </span>
          </label>
          <label className="flex items-start justify-between gap-3">
            <span className="pt-1 text-ink-dim">メモ</span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              className="flex-1 rounded border border-hairline bg-panel px-2 py-1 text-ink"
            />
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-full border border-hairline px-3 py-1 text-xs text-ink-dim hover:bg-panel"
          >
            キャンセル
          </button>
          <button
            onClick={handleSave}
            className="rounded-full border border-act-700/60 bg-act-700/30 px-3 py-1 text-xs text-act-300 hover:bg-act-700/60"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDuration(min: number): string {
  if (min < 60) return `${min}分`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m === 0 ? `${h}h` : `${h}h${m}m`;
}

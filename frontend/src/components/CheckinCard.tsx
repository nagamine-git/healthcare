import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Smile } from "lucide-react";
import { api } from "../lib/api";
import type { CheckinSuggested, CheckinUpdate } from "../lib/api";

/**
 * いまの調子: 気分/活力/ストレス/筋肉痛を 5 段階でタップ記録 (即時保存)。
 * 主観は時間変動するため「直近2〜3時間の体感」= 瞬間の記録として扱う
 * (右の集中力＝リアルタイムと揃える)。客観データが代理する結果変数。
 *
 * - サジェスト(客観指標 BB/ストレス/睡眠/トレ負荷 からの推定。無ければ自己平均)は
 *   淡色のゴースト表示、ユーザー入力は濃色。
 * - 選択中の値を再タップ、または「クリア」で取り消し。
 */

type DimKey = "mood" | "energy" | "stress" | "soreness";
type Dim = { key: DimKey; label: string; goodHigh: boolean };

const DIMS: Dim[] = [
  { key: "mood", label: "気分", goodHigh: true },
  { key: "energy", label: "活力", goodHigh: true },
  { key: "stress", label: "ストレス", goodHigh: false },
  { key: "soreness", label: "筋肉痛", goodHigh: false },
];

function filledColor(value: number, goodHigh: boolean): string {
  const good = goodHigh ? value >= 4 : value <= 2;
  const bad = goodHigh ? value <= 2 : value >= 4;
  if (good) return "bg-emerald-500";
  if (bad) return "bg-rose-500";
  return "bg-amber-500";
}

/** 「直近2〜3時間の体感」の建付けなので、3時間経過した入力は現在の状態
 * として扱わず淡色化する (データは日次記録として残り、LLM の7日平均には使う) */
const STALE_MS = 3 * 60 * 60 * 1000;

export function CheckinCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["checkin"], queryFn: api.getCheckin });
  // 頭痛はエピソード型 (開始/終了時刻がトリガー分析に必要) なので、
  // 表示は同じ 5 段ドットでも裏は MigraineEpisode の開始/強度更新/終了に対応させる
  const migraine = useQuery({ queryKey: ["migraine"], queryFn: () => api.migraineList(7) });
  const invalidateMigraine = () => {
    qc.invalidateQueries({ queryKey: ["migraine"] });
    qc.invalidateQueries({ queryKey: ["today"] });
  };
  const migStart = useMutation({
    mutationFn: (severity: number) => api.migraineStart({ severity }),
    onSuccess: invalidateMigraine,
  });
  const migPatch = useMutation({
    mutationFn: ({ id, severity }: { id: number; severity: number }) =>
      api.migrainePatch(id, { severity }),
    onSuccess: invalidateMigraine,
  });
  const migEnd = useMutation({
    mutationFn: () => api.migraineEnd(),
    onSuccess: invalidateMigraine,
  });
  const save = useMutation({
    mutationFn: (body: CheckinUpdate) => api.postCheckin(body),
    onSuccess: (data) => {
      qc.setQueryData(["checkin"], data);
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const today = q.data?.today;
  const suggested: CheckinSuggested =
    q.data?.suggested ?? { mood: null, energy: null, stress: null, soreness: null };
  const hasAny = today && DIMS.some((d) => today[d.key] != null);
  const updatedAt = today?.updated_at ? new Date(today.updated_at) : null;
  const stale = !!(updatedAt && Date.now() - updatedAt.getTime() > STALE_MS);
  const recordedLabel = updatedAt
    ? `${updatedAt.getHours()}:${updatedAt.getMinutes().toString().padStart(2, "0")} 時点`
    : null;

  return (
    <section className="space-y-2 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center gap-1.5">
        <Smile size={14} className="text-emerald-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">いまの調子</span>
        <span className="ml-auto flex items-center gap-2">
          {hasAny && (
            <button
              onClick={() => save.mutate({ clear: ["mood", "energy", "stress", "soreness"] })}
              className="text-[10px] text-slate-500 hover:text-slate-300"
            >
              クリア
            </button>
          )}
          <span className="text-[10px] text-slate-500">
            {stale && recordedLabel ? `${recordedLabel}の記録` : "直近2〜3時間の体感"}
          </span>
        </span>
      </div>

      <div className="grid gap-1.5">
        {DIMS.map((d) => {
          const value = (today?.[d.key] as number | null) ?? null;
          const hint = suggested[d.key]; // 淡色のゴースト目安
          return (
            <div key={d.key} className="flex items-center gap-2">
              <span className="w-14 text-[11px] text-slate-300">{d.label}</span>
              <div className="flex gap-1.5">
                {[1, 2, 3, 4, 5].map((lvl) => {
                  const isFilled = value != null && lvl <= value;
                  const isHint = value == null && hint != null && lvl === hint;
                  let cls = "bg-slate-800 ring-1 ring-slate-700"; // 空
                  if (isFilled) {
                    // 3時間経過した入力は「いま」ではないので淡色化
                    cls = `${filledColor(value, d.goodHigh)}${stale ? " opacity-35" : ""}`;
                  } else if (isHint) {
                    cls = "bg-slate-600/40 ring-1 ring-slate-500"; // サジェスト=淡色
                  }
                  return (
                    <button
                      key={lvl}
                      aria-label={`${d.label} ${lvl}`}
                      // 選択中の値を再タップ → クリア (トグルオフ)。ただし stale な
                      // 記録の再タップは「いまも同じ」の再確認として上書き保存。
                      // 未入力でゴースト位置をタップ = サジェスト採用として記録
                      // (機器推定の追認か能動入力かを乖離分析で区別するため)
                      onClick={() =>
                        value === lvl && !stale
                          ? save.mutate({ clear: [d.key] })
                          : save.mutate({
                              [d.key]: lvl,
                              ...(isHint ? { from_suggested: [d.key] } : {}),
                            } as CheckinUpdate)
                      }
                      className={`h-5 w-5 rounded-full transition active:scale-90 hover:brightness-125 ${cls}`}
                    />
                  );
                })}
              </div>
              {value != null ? (
                <span className="text-[10px] tabular-nums text-slate-400">{value}</span>
              ) : hint != null ? (
                <span className="text-[10px] tabular-nums text-slate-600">推定 {hint}</span>
              ) : null}
            </div>
          );
        })}
        {(() => {
          // 頭痛: 表示は同じ 5 段ドットだが、裏はエピソード (開始/終了時刻が
          // トリガー分析に必要)。タップで開始、強度変更、同じ強度の再タップで「治った」
          const active = migraine.data?.active ?? null;
          const headache = active
            ? Math.min(5, Math.max(1, Math.ceil((active.severity ?? 6) / 2)))
            : null;
          return (
            <div className="flex items-center gap-2">
              <span className="w-14 text-[11px] text-slate-300">頭痛</span>
              <div className="flex gap-1.5">
                {[1, 2, 3, 4, 5].map((lvl) => {
                  const isFilled = headache != null && lvl <= headache;
                  const cls = isFilled
                    ? filledColor(headache, false)
                    : "bg-slate-800 ring-1 ring-slate-700";
                  return (
                    <button
                      key={lvl}
                      aria-label={`頭痛 ${lvl}`}
                      onClick={() => {
                        if (!active) migStart.mutate(lvl * 2);
                        else if (lvl === headache) migEnd.mutate();
                        else migPatch.mutate({ id: active.id, severity: lvl * 2 });
                      }}
                      className={`h-5 w-5 rounded-full transition active:scale-90 hover:brightness-125 ${cls}`}
                    />
                  );
                })}
              </div>
              {active ? (
                <span className="text-[10px] text-rose-400">
                  発作中 {active.started_at_jst?.slice(11, 16)}〜（同じ強度を再タップで「治った」）
                </span>
              ) : (
                <span className="text-[10px] text-slate-600">なし</span>
              )}
            </div>
          );
        })()}
      </div>
      <div className="text-[9px] text-slate-600">
        ● 濃色＝あなたの入力 / ○ 淡色＝関連指標からの推定（タップで確定・再タップで取消）
        {stale ? " ／ 3時間以上前の記録は淡色（タップで「いまも同じ」と再確認）" : ""}
      </div>
    </section>
  );
}

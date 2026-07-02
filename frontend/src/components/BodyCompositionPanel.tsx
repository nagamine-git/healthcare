import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LineChart, Line, YAxis, ResponsiveContainer, Tooltip } from "recharts";
import { api, type BodyCompDraft } from "../lib/api";
import { Panel, Stat } from "./ui/cockpit";
import { P } from "../lib/palette";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const EMPTY: BodyCompDraft = {
  skeletal_muscle_kg: null,
  skeletal_muscle_pct: null,
  visceral_fat_level: null,
  bmr_kcal: null,
};

const FIELDS: { key: keyof BodyCompDraft; label: string; unit: string }[] = [
  { key: "skeletal_muscle_kg", label: "骨格筋量", unit: "kg" },
  { key: "skeletal_muscle_pct", label: "骨格筋率", unit: "%" },
  { key: "visceral_fat_level", label: "内臓脂肪", unit: "lv" },
  { key: "bmr_kcal", label: "基礎代謝", unit: "kcal" },
];

/** 体組成計(BIA)スクショ取り込み: 骨格筋量・内臓脂肪・基礎代謝(Apple Health 標準で取れない指標)。 */
export function BodyCompositionPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["body-comp"], queryFn: api.bodyComposition, retry: false });
  const [draft, setDraft] = useState<BodyCompDraft | null>(null);

  const extract = useMutation({
    mutationFn: async (file: File) => api.bodyCompExtract(await fileToBase64(file), file.type || "image/png"),
    onSuccess: (r) => setDraft({ ...EMPTY, ...r.draft }),
  });
  const save = useMutation({
    mutationFn: (d: BodyCompDraft) => api.bodyCompPut(d),
    onSuccess: () => {
      setDraft(null);
      qc.invalidateQueries({ queryKey: ["body-comp"] });
    },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.bodyCompDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["body-comp"] }),
  });

  const latest = q.data?.latest ?? null;
  const history = q.data?.history ?? [];
  const muscleTrend = [...history]
    .reverse()
    .filter((h) => h.skeletal_muscle_kg != null)
    .map((h) => ({ date: h.date, v: h.skeletal_muscle_kg as number }));
  const prev = history[1];
  const delta =
    latest?.skeletal_muscle_kg != null && prev?.skeletal_muscle_kg != null
      ? +(latest.skeletal_muscle_kg - prev.skeletal_muscle_kg).toFixed(1)
      : null;

  return (
    <Panel title="体組成(骨格筋・内臓脂肪・基礎代謝)">
      {latest ? (
        <>
          <div className="grid grid-cols-4 gap-2">
            <Stat
              size="sm"
              label="骨格筋"
              value={latest.skeletal_muscle_kg ?? "—"}
              unit={latest.skeletal_muscle_kg != null ? "kg" : ""}
              delta={delta != null ? `${delta > 0 ? "+" : ""}${delta}kg` : undefined}
              tone={delta != null ? (delta >= 0 ? "prog" : "risk") : "neutral"}
            />
            <Stat size="sm" label="骨格筋率" value={latest.skeletal_muscle_pct ?? "—"} unit={latest.skeletal_muscle_pct != null ? "%" : ""} />
            <Stat size="sm" label="内臓脂肪" value={latest.visceral_fat_level ?? "—"} unit="lv" tone={latest.visceral_fat_level != null && latest.visceral_fat_level >= 10 ? "risk" : "neutral"} />
            <Stat size="sm" label="基礎代謝" value={latest.bmr_kcal ?? "—"} unit={latest.bmr_kcal != null ? "kcal" : ""} />
          </div>
          {muscleTrend.length >= 2 && (
            <div className="mt-2 h-16">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={muscleTrend} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                  <YAxis domain={["dataMin - 0.5", "dataMax + 0.5"]} hide />
                  <Tooltip
                    contentStyle={{ background: "#1a2230", border: "1px solid #243044", borderRadius: 8, fontSize: 11 }}
                    labelStyle={{ color: "#9aa7b8" }}
                    formatter={(v: number) => [`${v}kg`, "骨格筋"]}
                  />
                  <Line type="monotone" dataKey="v" stroke={P.prog} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
              <p className="telemetry-label">骨格筋量の推移(kg)</p>
            </div>
          )}
        </>
      ) : (
        <p className="text-sm text-ink-dim">
          体組成計アプリのスクショを取り込むと、Apple Health で取れない骨格筋量・内臓脂肪・基礎代謝を記録できます。
        </p>
      )}

      {/* 取り込み: スクショ → 抽出 → 確認 → 保存 */}
      <div className="mt-3 border-t border-hairline pt-2">
        <label className="block">
          <span className="telemetry-label">📷 体組成計のスクショから取り込み</span>
          <input
            type="file"
            accept="image/*"
            disabled={extract.isPending}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) extract.mutate(f);
            }}
            className="mt-1 block w-full text-xs text-ink-dim file:mr-2 file:rounded file:border-0 file:bg-act file:px-3 file:py-1 file:text-void"
          />
        </label>
        {extract.isPending && <p className="mt-1 text-xs text-ink-faint">読み取り中…</p>}
        {extract.isError && <p className="mt-1 text-xs text-risk">読み取れませんでした</p>}

        {draft && (
          <div className="mt-2 rounded-lg border border-hairline bg-hull/40 p-2">
            <p className="text-[11px] text-ink-faint">読み取り結果を確認・修正して保存(誤読しやすいので必ず確認)。</p>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              {FIELDS.map((f) => (
                <label key={f.key} className="text-xs text-ink-dim">
                  {f.label}
                  <div className="mt-0.5 flex items-center gap-1">
                    <input
                      type="number"
                      step="0.1"
                      value={(draft[f.key] as number | null) ?? ""}
                      onChange={(e) =>
                        setDraft({ ...draft, [f.key]: e.target.value === "" ? null : Number(e.target.value) })
                      }
                      className="w-full rounded bg-panel px-2 py-1 telemetry-num text-ink"
                    />
                    <span className="text-[10px] text-ink-faint">{f.unit}</span>
                  </div>
                </label>
              ))}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <button
                disabled={save.isPending}
                onClick={() => save.mutate(draft)}
                className="rounded-lg bg-act px-3 py-1.5 text-sm font-medium text-void hover:bg-act-300 disabled:opacity-50"
              >
                {save.isPending ? "保存中…" : "今日の記録として保存"}
              </button>
              <button onClick={() => setDraft(null)} className="text-xs text-ink-faint hover:text-ink-dim">
                やめる
              </button>
            </div>
          </div>
        )}

        {history.length > 0 && (
          <div className="mt-3 space-y-1 border-t border-hairline pt-2">
            {history.slice(0, 6).map((h) => (
              <div key={h.id} className="flex items-center justify-between text-[11px] text-ink-faint">
                <span className="telemetry-num">{h.date}</span>
                <span className="text-ink-dim">
                  筋 {h.skeletal_muscle_kg ?? "—"}kg ・ 内臓 {h.visceral_fat_level ?? "—"} ・ BMR {h.bmr_kcal ?? "—"}
                </span>
                <button onClick={() => del.mutate(h.id)} className="hover:text-risk">削除</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

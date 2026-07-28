import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BodyMeasurementIn } from "../lib/api";
import { Panel, Pill, Stat } from "./ui/cockpit";

const EMPTY: BodyMeasurementIn = {
  waist_cm: null,
  neck_cm: null,
  chest_cm: null,
  hip_cm: null,
  note: null,
};

const WHTR_LABEL: Record<string, { text: string; tone: "prog" | "info" | "risk" }> = {
  good: { text: "良好 (身長の半分未満)", tone: "prog" },
  caution: { text: "要注意", tone: "info" },
  high: { text: "高め", tone: "risk" },
};

/** 符号付きの差分表記 (+1.2 / -3.4 / ±0)。目標とのギャップ表示用。 */
function fmtSigned(v: number): string {
  if (v === 0) return "±0";
  return v > 0 ? `+${v}` : `${v}`;
}

/**
 * 周径測定 (ウエスト/首/胸/ヒップ) パネル。
 *
 * 体重・体脂肪率(BIA)だけでは測定誤差 (±3-5%、体水分の日内変動の影響大) が大きいため、
 * メジャーで直接測る周径を2本目の評価軸として記録する。WHtR (ウエスト身長比) と
 * 米海軍式体脂肪率 (体水分に左右されない) を BIA の体脂肪率と並べて表示する。
 */
export function BodyMeasurementPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["body-measurement"], queryFn: api.bodyMeasurement, retry: false });
  const [draft, setDraft] = useState<BodyMeasurementIn>(EMPTY);
  const [editing, setEditing] = useState(false);

  const save = useMutation({
    mutationFn: (d: BodyMeasurementIn) => api.bodyMeasurementPut(d),
    onSuccess: () => {
      setEditing(false);
      setDraft(EMPTY);
      qc.invalidateQueries({ queryKey: ["body-measurement"] });
    },
  });

  const latest = q.data?.latest ?? null;
  const whtrInfo = q.data?.whtr_status ? WHTR_LABEL[q.data.whtr_status] : null;
  const discrepancy = q.data?.discrepancy ?? null;
  const gap = q.data?.gap ?? null;
  const whtrBorderline = gap?.available ? gap.secondary.whtr?.borderline ?? false : false;

  const startEdit = () => {
    setDraft({
      waist_cm: latest?.waist_cm ?? null,
      neck_cm: latest?.neck_cm ?? null,
      chest_cm: latest?.chest_cm ?? null,
      hip_cm: latest?.hip_cm ?? null,
      note: latest?.note ?? null,
    });
    setEditing(true);
  };

  return (
    <Panel
      title="周径測定 (ウエスト/首)"
      action={
        !editing && (
          <button
            onClick={startEdit}
            className="rounded-lg bg-panel px-2.5 py-1 text-[11px] font-medium text-ink-dim hover:text-ink"
          >
            {latest ? "更新" : "記録する"}
          </button>
        )
      }
    >
      {latest ? (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Stat size="sm" label="ウエスト" value={latest.waist_cm ?? "—"} unit={latest.waist_cm != null ? "cm" : ""} />
            <Stat size="sm" label="首" value={latest.neck_cm ?? "—"} unit={latest.neck_cm != null ? "cm" : ""} />
          </div>
          {(latest.chest_cm != null || latest.hip_cm != null) && (
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Stat size="sm" label="胸" value={latest.chest_cm ?? "—"} unit={latest.chest_cm != null ? "cm" : ""} />
              <Stat size="sm" label="ヒップ" value={latest.hip_cm ?? "—"} unit={latest.hip_cm != null ? "cm" : ""} />
            </div>
          )}

          <div className="mt-3 border-t border-hairline pt-2">
            <div className="flex items-center justify-between">
              <span className="telemetry-label">WHtR (ウエスト身長比)</span>
              {whtrBorderline ? (
                <Pill tone="info">境界線上 (0.5に近い)</Pill>
              ) : (
                whtrInfo && <Pill tone={whtrInfo.tone}>{whtrInfo.text}</Pill>
              )}
            </div>
            <div className="mt-1 telemetry-num text-lg font-semibold text-ink">
              {q.data?.whtr != null ? q.data.whtr.toFixed(2) : "—"}
            </div>
            <p className="mt-0.5 text-[10px] text-ink-faint">
              {whtrBorderline
                ? "閾値 0.5 のすぐ近く。「良好」と言い切れる差ではなく、メジャーの当て方で数mm変われば逆側に転ぶ範囲。経過観察の対象。"
                : "目安は 0.5 未満(ウエストは身長の半分未満)。BMI より内臓脂肪リスクを反映しやすい指標。"}
            </p>
          </div>

          <div className="mt-3 border-t border-hairline pt-2">
            <span className="telemetry-label">体脂肪率: BIA vs 海軍式(周径法)</span>
            <div className="mt-1 grid grid-cols-2 gap-2">
              <Stat
                size="sm"
                label="BIA (体組成計)"
                value={q.data?.bia_body_fat_pct ?? "—"}
                unit={q.data?.bia_body_fat_pct != null ? "%" : ""}
              />
              <Stat
                size="sm"
                label="海軍式(周径)"
                value={q.data?.navy_body_fat_pct ?? "—"}
                unit={q.data?.navy_body_fat_pct != null ? "%" : ""}
              />
            </div>
            {discrepancy && (
              <p className={`mt-1.5 text-[11px] ${discrepancy.status === "large" ? "text-risk" : "text-ink-dim"}`}>
                {discrepancy.status === "large"
                  ? `2本の差が ${Math.abs(discrepancy.diff_pt)}pt と大きめ — BIA は体水分で荒れやすいので海軍式の方が今は安定した目安`
                  : `2本がおおむね一致 (差 ${Math.abs(discrepancy.diff_pt)}pt) — 信頼度は高い`}
              </p>
            )}
            <p className="mt-1 text-[10px] text-ink-faint">
              海軍式は体水分の影響を受けないため、日内変動しやすい BIA の裏付けになる(Hodgdon &amp;
              Beckett 1984)。女性の推定式は別途 hip 周径が必要なため未対応。
            </p>
          </div>

          {/* 目標とのギャップ: 「良好」で終わらせず、目標との距離をはっきり示す。
              煽らない — 事実と目安を淡々と (体型は最優先事項ではない)。 */}
          <div className="mt-3 border-t border-hairline pt-2">
            <span className="telemetry-label">目標とのギャップ</span>
            {gap?.available ? (
              <>
                <div className="mt-1.5 rounded-lg bg-hull/40 p-2.5">
                  <div className="text-sm font-medium text-ink">{gap.verdict.label}</div>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-ink-dim">{gap.verdict.explanation}</p>
                </div>

                <div className="mt-2 grid grid-cols-3 gap-2">
                  <Stat
                    size="sm"
                    label="体重"
                    value={gap.weight.now_kg}
                    unit="kg"
                    delta={`目標${gap.weight.target_kg} (${fmtSigned(gap.weight.gap_kg)}kg)`}
                    tone={gap.weight.near_target ? "prog" : "neutral"}
                  />
                  <Stat
                    size="sm"
                    label="除脂肪体重"
                    value={gap.lbm.now_kg}
                    unit="kg"
                    delta={`目標${gap.lbm.target_kg} (${fmtSigned(gap.lbm.gap_kg)}kg)`}
                    tone={gap.lbm.meaningful ? (gap.lbm.gap_kg < 0 ? "act" : "info") : "prog"}
                  />
                  <Stat
                    size="sm"
                    label="体脂肪量"
                    value={gap.lbm.fat_mass_now_kg}
                    unit="kg"
                    delta={`目標${gap.lbm.fat_mass_target_kg} (${fmtSigned(gap.lbm.fat_mass_gap_kg)}kg)`}
                    tone="neutral"
                  />
                </div>
                <p className="mt-1 text-[10px] text-ink-faint">
                  除脂肪体重(≒筋量)が本質の指標 — 体重の過不足だけでは脂肪不足か筋量不足かが分からない。
                </p>

                {gap.timeframe && (
                  <div className="mt-2 rounded-lg bg-void/30 px-2.5 py-2">
                    <div className="text-xs text-ink-dim">
                      期間の <b className="text-ink">{gap.timeframe.label}</b>
                    </div>
                    <p className="mt-0.5 text-[10px] leading-tight text-ink-faint">{gap.timeframe.basis}</p>
                  </div>
                )}

                {(gap.secondary.skeletal_muscle || gap.secondary.visceral_fat) && (
                  <ul className="mt-2 space-y-1">
                    {gap.secondary.skeletal_muscle && (
                      <li className="text-[10px] leading-tight text-ink-faint">
                        · {gap.secondary.skeletal_muscle.note}
                      </li>
                    )}
                    {gap.secondary.visceral_fat && (
                      <li className="text-[10px] leading-tight text-ink-faint">
                        · {gap.secondary.visceral_fat.note}
                      </li>
                    )}
                  </ul>
                )}
              </>
            ) : (
              <p className="mt-1 text-xs text-ink-dim">
                {gap && !gap.available ? gap.reason : "体重・体脂肪率の記録が必要です"}
              </p>
            )}
          </div>
        </>
      ) : (
        <p className="text-sm text-ink-dim">
          ウエスト・首をメジャーで測ると、BIA (体組成計) より測定誤差の小さい体脂肪率の裏付けと、
          内臓脂肪リスクの指標 (WHtR) が得られます。
        </p>
      )}

      {editing && (
        <div className="mt-3 rounded-lg border border-hairline bg-hull/40 p-2">
          <p className="text-[11px] text-ink-faint">
            起床後・排尿後・空腹時(食後は張って数値がぶれる)。ウエストは臍の高さ、首は喉仏の下で測る。
          </p>
          <div className="mt-1.5 grid grid-cols-2 gap-2">
            {(
              [
                ["waist_cm", "ウエスト (必須級)"],
                ["neck_cm", "首 (必須級)"],
                ["chest_cm", "胸 (任意)"],
                ["hip_cm", "ヒップ (任意)"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="text-xs text-ink-dim">
                {label}
                <div className="mt-0.5 flex items-center gap-1">
                  <input
                    type="number"
                    step="0.1"
                    value={draft[key] ?? ""}
                    onChange={(e) =>
                      setDraft({ ...draft, [key]: e.target.value === "" ? null : Number(e.target.value) })
                    }
                    className="w-full rounded bg-panel px-2 py-1 telemetry-num text-ink"
                  />
                  <span className="text-[10px] text-ink-faint">cm</span>
                </div>
              </label>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <button
              disabled={save.isPending || (draft.waist_cm == null && draft.neck_cm == null && draft.chest_cm == null && draft.hip_cm == null)}
              onClick={() => save.mutate(draft)}
              className="rounded-lg bg-act px-3 py-1.5 text-sm font-medium text-void hover:bg-act-300 disabled:opacity-50"
            >
              {save.isPending ? "保存中…" : "今日の記録として保存"}
            </button>
            <button onClick={() => setEditing(false)} className="text-xs text-ink-faint hover:text-ink-dim">
              やめる
            </button>
          </div>
          {save.isError && <p className="mt-1 text-xs text-risk">保存に失敗しました</p>}
        </div>
      )}

      <p className="mt-3 border-t border-hairline pt-2 text-[10px] text-ink-faint">
        測定頻度の目安: 体重/体脂肪は毎日でも7日移動平均で判断、
        <span className="text-ink-dim">ウエスト+首は週1回(起床後・空腹時)</span>で十分に変化を検出できる
        (周径は測定誤差が小さいため)。胸/ヒップは四半期でOK。毎日測る必要はありません。
      </p>
    </Panel>
  );
}

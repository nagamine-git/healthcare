import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type FinanceResponse,
  type RebalanceHolding,
  type RoiInput,
  type RoiRow,
} from "../lib/api";
import { Button, Panel, Pill, Skeleton } from "../components/ui/cockpit";

const yen = (n: number | null | undefined) =>
  n == null ? "—" : `¥${Math.round(n).toLocaleString()}`;

function fileToB64(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",")[1] ?? "");
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}

const REB_SIGNAL: Record<RebalanceHolding["signal"], { label: string; tone: "prog" | "act" | "risk" | "neutral" }> = {
  buy: { label: "買い増し", tone: "prog" },
  sell: { label: "利確/控え", tone: "risk" },
  hold: { label: "維持", tone: "neutral" },
  reserve: { label: "配分外", tone: "neutral" },
};
const ROI_VERDICT: Record<RoiRow["verdict"], { label: string; tone: "prog" | "act" | "risk" | "neutral" }> = {
  buy: { label: "投資価値あり", tone: "prog" },
  watch: { label: "様子見", tone: "act" },
  skip: { label: "見送り", tone: "neutral" },
  continue: { label: "継続", tone: "prog" },
  cancel: { label: "解約候補", tone: "risk" },
};

function useFinanceMut(qc: ReturnType<typeof useQueryClient>) {
  return (fn: (v: unknown) => Promise<FinanceResponse>) =>
    useMutation({ mutationFn: fn, onSuccess: (d) => qc.setQueryData(["finance"], d) });
}

function HoldingRow({ h, onSave, onDelete }: {
  h: RebalanceHolding;
  onSave: (v: { id: number; name: string; category: string; value_jpy: number; target_weight: number; risk_tier: number }) => void;
  onDelete: (id: number) => void;
}) {
  const [val, setVal] = useState(String(h.value_jpy ?? 0));
  const [w, setW] = useState(String(h.target_weight));
  const sig = REB_SIGNAL[h.signal];
  const saveAll = (tier: number) =>
    onSave({ id: h.id, name: h.name, category: h.category, value_jpy: Number(val) || 0, target_weight: Number(w) || 0, risk_tier: tier });
  return (
    <div className="border-t border-hairline py-1.5 text-xs first:border-t-0">
      <div className="flex items-center gap-2">
        <span className="flex-1 truncate text-ink">{h.name}</span>
        <Pill tone={sig.tone}>{sig.label}</Pill>
        <select value={h.risk_tier} onChange={(e) => saveAll(Number(e.target.value))}
          title="リスク階層(自動判定。手で上書き可)"
          className="rounded bg-panel px-1 py-0.5 text-[10px] text-ink-dim">
          {[0, 1, 2, 3, 4].map((t) => <option key={t} value={t}>{["現金", "債券", "株/投信", "暗号(主)", "暗号(アルト)"][t]}</option>)}
        </select>
        <button onClick={() => onDelete(h.id)} className="text-ink-faint hover:text-risk">×</button>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11px]">
        <label className="text-ink-faint">残高
          <input key={`v-${h.id}-${h.value_jpy}`} value={val} onChange={(e) => setVal(e.target.value)}
            onBlur={() => saveAll(h.risk_tier)}
            inputMode="numeric" className="ml-1 w-24 rounded bg-panel px-1.5 py-0.5 telemetry-num text-ink" />
        </label>
        <label className="text-ink-faint">目標ウェイト
          <input key={`w-${h.id}-${h.target_weight}`} value={w} onChange={(e) => setW(e.target.value)}
            onBlur={() => saveAll(h.risk_tier)}
            inputMode="decimal" className="ml-1 w-12 rounded bg-panel px-1.5 py-0.5 telemetry-num text-ink" />
        </label>
      </div>
      {h.target_value != null && (
        <div className="mt-0.5 text-[11px] text-ink-faint">
          現在 {h.current_ratio}% / 目標 {h.target_ratio}% ・ 目標額 {yen(h.target_value)} ・{" "}
          <span className={h.room != null && h.room >= 0 ? "text-prog-300" : "text-risk"}>
            {h.room != null && h.room >= 0 ? `あと ${yen(h.room)} 投資可` : `${yen(Math.abs(h.room ?? 0))} 超過`}
          </span>
        </div>
      )}
    </div>
  );
}

function RebalanceSection({ data }: { data: FinanceResponse }) {
  const qc = useQueryClient();
  const mut = useFinanceMut(qc);
  const save = mut((v) => api.financeAsset(v as never));
  const del = mut((v) => api.financeAssetDelete(v as number));
  const cfg = mut((v) => api.financeConfig(v as never));
  const imp = mut((v) => api.financeImportAssets(v as never));
  const alloc = mut((v) => api.financeAutoAllocate(v as number | undefined));
  const r = data.rebalance;
  const [newName, setNewName] = useState("");
  const [csv, setCsv] = useState("");

  return (
    <Panel title="資産リバランス — MoneyForward 転記 → 目標配分へ">
      <p className="mb-2 text-[11px] text-ink-faint">
        目標ウェイト(1以上)を入れた資産だけが配分対象。空欄/0は「配分外」(現金・予備として保持)。
        余剰=総資産−防衛資金 を、ウェイト比で各資産へ割り当て、過不足を出す。
      </p>
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div><div className="telemetry-label">総資産</div><div className="telemetry-num text-ink">{yen(r.total)}</div></div>
        <div>
          <div className="telemetry-label">防衛資金</div>
          <input key={`rsv-${r.reserve ?? 0}`} defaultValue={String(r.reserve ?? 0)} inputMode="numeric"
            onBlur={(e) => cfg.mutate({ reserve_jpy: Number(e.target.value) || 0 } as never)}
            className="w-full rounded bg-panel px-1.5 py-0.5 telemetry-num text-ink" />
        </div>
        <div><div className="telemetry-label">余剰(投資可)</div><div className="telemetry-num text-prog-300">{yen(r.investable)}</div></div>
        <div><div className="telemetry-label">未配分(投資余地)</div><div className="telemetry-num text-act-300">{yen(r.unallocated)}</div></div>
      </div>
      {(r.reserve ?? 0) > (r.total ?? 0) && (
        <p className="mt-1 text-[11px] text-act-300">
          防衛資金(¥{Math.round(r.reserve ?? 0).toLocaleString()})が総資産を上回るため余剰=0。
          月支出が大きく目標月数を満たせていません(ランウェイを参照)。防衛資金を手で下げるか月数を減らせます。
        </p>
      )}

      <div className="mt-3">
        {r.holdings.map((h) => (
          <HoldingRow key={h.id} h={h}
            onSave={(v) => save.mutate(v as never)} onDelete={(id) => del.mutate(id as never)} />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-act-700/40 bg-act/10 p-2">
        <span className="telemetry-label text-act-300">自動配分</span>
        <span className="text-[11px] text-ink-faint">リスク許容度</span>
        <select value={r.risk_tolerance}
          onChange={(e) => alloc.mutate(Number(e.target.value) as never)}
          className="rounded bg-panel px-1.5 py-0.5 text-xs text-ink">
          {[1, 2, 3, 4, 5, 6, 7].map((l) => (
            <option key={l} value={l}>{l} {l === 1 ? "(最も保守)" : l === 4 ? "(中庸)" : l === 7 ? "(最も積極)" : ""}</option>
          ))}
        </select>
        <Button variant="primary" disabled={alloc.isPending} onClick={() => alloc.mutate(undefined as never)}>
          {alloc.isPending ? "配分中…" : "リスク階層で自動配分"}
        </Button>
        <span className="w-full text-[10px] text-ink-faint">
          安全側から再帰分割(現金→株/投信→暗号(主)→暗号(アルト))。許容度が高いほどリスク資産へ多く回す。各行のリスク階層は手で上書き可。
        </span>
      </div>

      <div className="mt-2 flex items-center gap-2 border-t border-hairline pt-2">
        <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="資産名を追加(例: 仮想通貨)"
          className="flex-1 rounded bg-panel px-2 py-1 text-xs text-ink" />
        <Button variant="subtle" disabled={!newName.trim()}
          onClick={() => { save.mutate({ name: newName.trim(), category: "manual" } as never); setNewName(""); }}>
          ＋追加
        </Button>
      </div>

      <div className="mt-3 rounded-lg border border-hairline bg-hull/40 p-2">
        <p className="telemetry-label">取込(MoneyForward)</p>
        <label className="mt-1 inline-block cursor-pointer rounded bg-prog-700 px-2.5 py-1 text-xs hover:bg-prog-500">
          スクショから取込(複数可)
          <input type="file" accept="image/*" multiple className="hidden"
            onChange={async (e) => {
              const files = Array.from(e.target.files ?? []); e.target.value = "";
              if (!files.length) return;
              const images = await Promise.all(
                files.map(async (f) => ({ image_base64: await fileToB64(f), media_type: f.type || "image/png" })),
              );
              imp.mutate({ images } as never);
            }} />
        </label>
        {imp.isPending && <span className="ml-2 text-[11px] text-ink-faint">読取中…</span>}
        {imp.isError && <span className="ml-2 text-[11px] text-risk">読取失敗</span>}
        <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={2}
          placeholder="または CSV を貼付(名前,金額 の各行)。複数スクショは全画面を合算"
          className="mt-1 w-full rounded bg-panel px-2 py-1 font-mono text-[11px] text-ink" />
        {csv.trim() && (
          <Button variant="subtle" onClick={() => { imp.mutate({ csv } as never); setCsv(""); }}>CSV取込</Button>
        )}
      </div>
    </Panel>
  );
}

const EMPTY_ROI: RoiInput = { name: "", cost_jpy: 0, period: "onetime", monthly_use_days: 0,
  monthly_time_saved_h: 0, monthly_revenue_jpy: 0, resale_jpy: 0, status: "considering" };

function RoiSection({ data }: { data: FinanceResponse }) {
  const qc = useQueryClient();
  const mut = useFinanceMut(qc);
  const save = mut((v) => api.financeRoi(v as never));
  const del = mut((v) => api.financeRoiDelete(v as number));
  const [form, setForm] = useState<RoiInput | null>(null);
  const roi = data.roi;

  const num = (k: keyof RoiInput) => (
    <input value={String((form as RoiInput)[k] ?? "")} inputMode="decimal"
      onChange={(e) => setForm({ ...(form as RoiInput), [k]: e.target.value === "" ? 0 : Number(e.target.value) })}
      className="w-16 rounded bg-panel px-1.5 py-0.5 telemetry-num text-ink" />
  );

  return (
    <Panel title="購入ROIランキング — 余剰資金で上位から検討" glow="act">
      <p className="text-[11px] text-ink-faint">
        余剰 {yen(roi.budget)} のうち {yen(roi.earmarked)} 分が上位候補(★)で埋まる試算。
      </p>
      <div className="mt-2">
        {roi.candidates.map((c) => {
          const v = ROI_VERDICT[c.verdict];
          return (
            <div key={c.id} className="border-t border-hairline py-1.5 text-xs first:border-t-0">
              <div className="flex items-center gap-2">
                {c.within_budget && <span className="text-act-300">★</span>}
                <span className="flex-1 truncate text-ink">{c.name}</span>
                <Pill tone={v.tone}>{v.label}</Pill>
                <button onClick={() => setForm({ id: c.id, name: c.name, cost_jpy: c.cost_jpy ?? 0, period: c.period,
                  monthly_use_days: 0, monthly_time_saved_h: c.monthly_time_saved_h,
                  monthly_revenue_jpy: c.monthly_revenue_jpy ?? 0, resale_jpy: c.resale_jpy ?? 0, status: c.status })}
                  className="text-ink-faint hover:text-ink">編集</button>
                <button onClick={() => del.mutate(c.id as never)} className="text-ink-faint hover:text-risk">×</button>
              </div>
              <div className="mt-0.5 text-[11px] text-ink-faint">
                スコア <span className="telemetry-num text-prog-300">{c.score}</span>
                {" "}(ROI {c.roi} × 活用率 {c.utilization}) ・ 月コスト {yen(c.monthly_cost)}
              </div>
            </div>
          );
        })}
        {roi.candidates.length === 0 && <p className="py-2 text-xs text-ink-faint">候補を追加してください。</p>}
      </div>

      {form === null ? (
        <Button variant="subtle" onClick={() => setForm({ ...EMPTY_ROI })}>＋候補を追加</Button>
      ) : (
        <div className="mt-2 rounded-lg border border-hairline bg-hull/40 p-2 text-xs">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="候補名(例: Notion / 新PC)" className="w-full rounded bg-panel px-2 py-1 text-ink" />
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-ink-faint">
            <label>価格 {num("cost_jpy")}</label>
            <label>
              区分{" "}
              <select value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })}
                className="rounded bg-panel px-1 py-0.5 text-ink">
                <option value="onetime">買い切り</option><option value="month">月額</option><option value="year">年額</option>
              </select>
            </label>
            <label>月活用日 {num("monthly_use_days")}</label>
            <label>月削減h {num("monthly_time_saved_h")}</label>
            <label>月収益 {num("monthly_revenue_jpy")}</label>
            <label>売却額 {num("resale_jpy")}</label>
            <label>
              状態{" "}
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}
                className="rounded bg-panel px-1 py-0.5 text-ink">
                <option value="considering">検討中</option><option value="owning">保有中</option><option value="canceled">解約済</option>
              </select>
            </label>
          </div>
          <div className="mt-2 flex gap-2">
            <Button variant="primary" disabled={!form.name.trim()}
              onClick={() => { save.mutate(form as never); setForm(null); }}>保存</Button>
            <button onClick={() => setForm(null)} className="text-ink-faint hover:text-ink-dim">やめる</button>
          </div>
        </div>
      )}
    </Panel>
  );
}

const yenK = (n: number | null | undefined) => (n == null ? "—" : `¥${Math.round(n).toLocaleString()}`);

function CashflowSection({ data }: { data: FinanceResponse }) {
  const qc = useQueryClient();
  const mut = useFinanceMut(qc);
  const imp = mut((v) => api.financeImportCashflow(v as string));
  const cfg = mut((v) => api.financeConfig(v as never));
  const cf = data.cashflow;
  return (
    <Panel title="入出金 — 月支出から防衛資金を自動算出">
      {cf.has_data ? (
        <>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div><div className="telemetry-label">月平均支出</div><div className="telemetry-num text-risk">{yenK(cf.avg_monthly_expense)}</div></div>
            <div><div className="telemetry-label">月平均収入</div><div className="telemetry-num text-prog-300">{yenK(cf.avg_monthly_income)}</div></div>
            <div><div className="telemetry-label">月収支</div><div className={`telemetry-num ${(cf.avg_monthly_net ?? 0) >= 0 ? "text-prog-300" : "text-risk"}`}>{yenK(cf.avg_monthly_net)}</div></div>
            <div><div className="telemetry-label">ランウェイ</div><div className="telemetry-num text-ink">{cf.runway_months == null ? "—" : `${cf.runway_months}ヶ月`}</div></div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-ink-faint">防衛資金 = 月支出 ×</span>
            <select key={`rm-${cf.reserve_months}`} defaultValue={String(cf.reserve_months)}
              onChange={(e) => cfg.mutate({ reserve_months: Number(e.target.value), apply_suggested_reserve: true } as never)}
              className="rounded bg-panel px-1.5 py-0.5 text-ink">
              {[3, 6, 9, 12].map((m) => <option key={m} value={m}>{m}ヶ月</option>)}
            </select>
            <span className="text-ink-dim">推奨 {yenK(cf.suggested_reserve)}</span>
            <Button variant="subtle" onClick={() => cfg.mutate({ apply_suggested_reserve: true } as never)}>防衛資金に適用</Button>
          </div>
          {(cf.categories?.length ?? 0) > 0 && (
            <div className="mt-2 border-t border-hairline pt-2">
              <p className="telemetry-label">支出カテゴリ(直近6ヶ月)</p>
              <div className="mt-1 space-y-0.5">
                {cf.categories!.map((c) => (
                  <div key={c.name} className="flex justify-between text-[11px]">
                    <span className="text-ink-dim">{c.name}</span>
                    <span className="telemetry-num text-ink-faint">{yenK(c.amount)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="text-sm text-ink-dim">入出金CSV(MoneyForward)を取り込むと、月平均支出から防衛資金を自動算出します。</p>
      )}
      <div className="mt-3">
        <label className="inline-block cursor-pointer rounded bg-prog-700 px-2.5 py-1 text-xs hover:bg-prog-500">
          入出金CSVを取り込む
          <input type="file" accept=".csv,text/csv" className="hidden"
            onChange={async (e) => {
              const f = e.target.files?.[0]; e.target.value = "";
              if (f) imp.mutate(await f.text() as never);
            }} />
        </label>
        {imp.isPending && <span className="ml-2 text-[11px] text-ink-faint">取込中…</span>}
        {imp.isError && <span className="ml-2 text-[11px] text-risk">取込失敗</span>}
      </div>
    </Panel>
  );
}

export function FinancePage({ onBack }: { onBack: () => void }) {
  const q = useQuery({ queryKey: ["finance"], queryFn: api.finance, retry: false });
  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">← 戻る</button>
      <h1 className="text-xl font-bold text-ink">資産・投資</h1>
      <p className="text-xs text-ink-faint">
        総資産から防衛資金を引いた余剰を目標配分へ(リバランス)。その余剰で、ROI上位の購入を検討。
      </p>
      {q.isError ? (
        <p className="text-sm text-risk">読み込みに失敗しました。少し待って再読み込みしてください。</p>
      ) : !q.data ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <CashflowSection data={q.data} />
          <RebalanceSection data={q.data} />
          <RoiSection data={q.data} />
        </>
      )}
    </div>
  );
}

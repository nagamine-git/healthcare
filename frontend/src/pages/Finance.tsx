import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type FinanceResponse,
  type RebalanceHolding,
  type RoiInput,
  type RoiRow,
  type WishlistItem,
} from "../lib/api";
import { Button, Panel, Pill, Skeleton } from "../components/ui/cockpit";
import { fileToB64 } from "../lib/files";

const yen = (n: number | null | undefined) =>
  n == null ? "—" : `¥${Math.round(n).toLocaleString()}`;

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
        {[...r.holdings]
          .sort((a, b) => (b.target_value ?? -1) - (a.target_value ?? -1))
          .map((h) => (
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
        <p className="telemetry-label">資産の取込</p>
        <p className="mt-1 text-[10px] text-ink-faint">
          スクショ取込は上部の「MoneyForward スクショ取込」から(資産・負債・収支をまとめて)。
          ここは CSV 貼付用です。
        </p>
        <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={2}
          placeholder="CSV を貼付(名前,金額 の各行)。取込に無い過去資産は削除"
          className="mt-1 w-full rounded bg-panel px-2 py-1 font-mono text-[11px] text-ink" />
        {csv.trim() && (
          <Button variant="subtle" onClick={() => { imp.mutate({ csv } as never); setCsv(""); }}>CSV取込</Button>
        )}
      </div>
    </Panel>
  );
}

const EMPTY_ROI: RoiInput = { name: "", url: "", cost_jpy: 0, period: "onetime", monthly_use_days: 0,
  monthly_time_saved_h: 0, monthly_revenue_jpy: 0, resale_jpy: 0, status: "considering", note: "" };

function WishlistImport({ onAdded }: { onAdded: () => void }) {
  const [url, setUrl] = useState("");
  const [items, setItems] = useState<WishlistItem[] | null>(null);
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function run(extra: { image_base64?: string; media_type?: string } = {}) {
    setBusy(true); setMsg("");
    try {
      const res = await api.financeRoiImportWishlist({ url: url || undefined, ...extra });
      setItems(res.items);
      setChecked(Object.fromEntries(res.items.map((_, i) => [i, true])));
      if (!res.items.length)
        setMsg(res.fetched ? "商品を抽出できませんでした" : "URL取得に失敗。スクショ画像で試してください");
    } catch {
      setMsg("取込に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  async function addChecked() {
    if (!items) return;
    const chosen = items.filter((_, i) => checked[i]);
    setBusy(true);
    try {
      for (const it of chosen)
        await api.financeRoi({ name: it.name, cost_jpy: it.cost_jpy, period: it.period, url: it.url,
          monthly_use_days: 0, monthly_time_saved_h: 0, monthly_revenue_jpy: 0, resale_jpy: 0, status: "considering" });
      setItems(null); setUrl(""); setMsg(`${chosen.length}件を追加しました。各候補の「AIで補完」で詳細を埋められます。`);
      onAdded();
    } finally {
      setBusy(false);
    }
  }

  const nChecked = Object.values(checked).filter(Boolean).length;

  return (
    <div className="mt-3 rounded-lg border border-hairline bg-hull/40 p-2">
      <p className="telemetry-label">Amazon欲しいものリストから一括取込</p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="公開wishlistのURL"
          className="min-w-[8rem] flex-1 rounded bg-panel px-2 py-1 text-[11px] text-ink" />
        <Button variant="primary" disabled={busy || !url.trim()} onClick={() => run()}>
          {busy ? "取込中…" : "取込"}
        </Button>
        <label className="cursor-pointer rounded bg-prog-700 px-2 py-1 text-[11px] hover:bg-prog-500">
          スクショから
          <input type="file" accept="image/*" className="hidden"
            onChange={async (e) => {
              const f = e.target.files?.[0]; e.target.value = "";
              if (f) run({ image_base64: await fileToB64(f), media_type: f.type || "image/png" });
            }} />
        </label>
      </div>
      {msg && <p className="mt-1 text-[11px] text-ink-faint">{msg}</p>}
      {items && items.length > 0 && (
        <div className="mt-2 space-y-1">
          {items.map((it, i) => (
            <label key={i} className="flex items-center gap-2 text-[11px] text-ink">
              <input type="checkbox" checked={checked[i] ?? false}
                onChange={(e) => setChecked({ ...checked, [i]: e.target.checked })} />
              <span className="flex-1 truncate">{it.name}</span>
              <span className="telemetry-num text-ink-faint">{it.cost_jpy ? `¥${Math.round(it.cost_jpy).toLocaleString()}` : "—"}</span>
            </label>
          ))}
          <Button variant="primary" disabled={busy || nChecked === 0} onClick={addChecked}>
            選択した{nChecked}件を追加
          </Button>
        </div>
      )}
    </div>
  );
}

function RoiSection({ data }: { data: FinanceResponse }) {
  const qc = useQueryClient();
  const mut = useFinanceMut(qc);
  const save = mut((v) => api.financeRoi(v as never));
  const del = mut((v) => api.financeRoiDelete(v as number));
  const [form, setForm] = useState<RoiInput | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [aiBusy, setAiBusy] = useState(false);
  const [aiErr, setAiErr] = useState(false);
  const roi = data.roi;

  const num = (k: keyof RoiInput) => (
    <input value={String((form as RoiInput)[k] ?? "")} inputMode="decimal"
      onChange={(e) => setForm({ ...(form as RoiInput), [k]: e.target.value === "" ? 0 : Number(e.target.value) })}
      className="w-16 rounded bg-panel px-1.5 py-0.5 telemetry-num text-ink" />
  );
  const reason = (k: string) =>
    reasons[k] ? <span className="ml-0.5 cursor-help text-[10px] text-act-300" title={reasons[k]}>💡</span> : null;

  const startEdit = (c: RoiRow) => {
    setForm({ id: c.id, name: c.name, url: c.url ?? "", cost_jpy: c.cost_jpy ?? 0, period: c.period,
      monthly_use_days: c.monthly_use_days, monthly_time_saved_h: c.monthly_time_saved_h,
      monthly_revenue_jpy: c.monthly_revenue_jpy ?? 0, resale_jpy: c.resale_jpy ?? 0, status: c.status });
    setReasons({});
  };

  async function runSuggest(extra: { image_base64?: string; media_type?: string } = {}) {
    if (!form) return;
    setAiBusy(true); setAiErr(false);
    try {
      const res = await api.financeRoiSuggest({
        name: form.name || undefined, url: form.url || undefined, ...extra,
      });
      if (res.fields) {
        setForm({ ...form, ...res.fields, name: form.name });
        setReasons(res.reasons || {});
      } else setAiErr(true);
    } catch {
      setAiErr(true);
    } finally {
      setAiBusy(false);
    }
  }

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
                <button onClick={() => startEdit(c)} className="text-ink-faint hover:text-ink">編集</button>
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
        <Button variant="subtle" onClick={() => { setForm({ ...EMPTY_ROI }); setReasons({}); }}>＋候補を追加</Button>
      ) : (
        <div className="mt-2 rounded-lg border border-hairline bg-hull/40 p-2 text-xs">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="候補名(例: Notion / 新PC)" className="w-full rounded bg-panel px-2 py-1 text-ink" />

          <div className="mt-1.5 flex flex-wrap items-center gap-2 rounded border border-act-700/40 bg-act/10 p-1.5">
            <input value={form.url ?? ""} onChange={(e) => setForm({ ...form, url: e.target.value })}
              placeholder="商品URL(任意)" className="min-w-[7rem] flex-1 rounded bg-panel px-2 py-1 text-[11px] text-ink" />
            <Button variant="primary" disabled={aiBusy || (!form.name.trim() && !form.url)}
              onClick={() => runSuggest()}>{aiBusy ? "推定中…" : "AIで補完"}</Button>
            <label className="cursor-pointer rounded bg-prog-700 px-2 py-1 text-[11px] hover:bg-prog-500">
              画像から
              <input type="file" accept="image/*" className="hidden"
                onChange={async (e) => {
                  const f = e.target.files?.[0]; e.target.value = "";
                  if (f) runSuggest({ image_base64: await fileToB64(f), media_type: f.type || "image/png" });
                }} />
            </label>
            {aiErr && <span className="text-[11px] text-risk">推定失敗</span>}
            <span className="w-full text-[10px] text-ink-faint">
              名前かURLを入れて「AIで補完」、または商品画像から。💡=推定根拠(ホバー)。値は必ず確認・補正を。
            </span>
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-ink-faint">
            <label>価格 {num("cost_jpy")}{reason("cost_jpy")}</label>
            <label>
              区分{" "}
              <select value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })}
                className="rounded bg-panel px-1 py-0.5 text-ink">
                <option value="onetime">買い切り</option><option value="month">月額</option><option value="year">年額</option>
              </select>{reason("period")}
            </label>
            <label>月活用日 {num("monthly_use_days")}{reason("monthly_use_days")}</label>
            <label>月削減h {num("monthly_time_saved_h")}{reason("monthly_time_saved_h")}</label>
            <label>月収益 {num("monthly_revenue_jpy")}{reason("monthly_revenue_jpy")}</label>
            <label>売却額 {num("resale_jpy")}{reason("resale_jpy")}</label>
            <label>
              状態{" "}
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}
                className="rounded bg-panel px-1 py-0.5 text-ink">
                <option value="considering">検討中</option><option value="owning">保有中</option><option value="canceled">解約済</option>
              </select>
            </label>
          </div>
          <input value={form.note ?? ""} onChange={(e) => setForm({ ...form, note: e.target.value })}
            placeholder="メモ(任意)" className="mt-1.5 w-full rounded bg-panel px-2 py-1 text-[11px] text-ink" />

          <div className="mt-2 flex gap-2">
            <Button variant="primary" disabled={!form.name.trim()}
              onClick={() => { save.mutate(form as never); setForm(null); }}>保存</Button>
            <button onClick={() => setForm(null)} className="text-ink-faint hover:text-ink-dim">やめる</button>
          </div>
        </div>
      )}
      <WishlistImport onAdded={() => qc.invalidateQueries({ queryKey: ["finance"] })} />
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

const LEVERAGE: Record<string, { label: string; cls: string; note: string }> = {
  good: { label: "良い借金(低利)", cls: "text-prog-300", note: "金利 < 期待リターン。手元は投資に回す方が有利" },
  bad: { label: "悪い借金(高利)", cls: "text-risk", note: "金利が純資産を毎年削る。先に返す" },
  caution: { label: "要注意", cls: "text-act-300", note: "金利しだい。金利を超えて稼げる時だけ○" },
  none: { label: "無借金", cls: "text-ink-dim", note: "" },
};

/** 看板(総資産×純資産)+ 診断(なんで増えない)+ 最善手(優先順位つき)。 */
function AdvisorSection({ data }: { data: FinanceResponse }) {
  const a = data.advisor;
  if (!a?.has_data) {
    return (
      <Panel>
        <h2 className="text-sm font-semibold text-ink">資産の最善手</h2>
        <p className="mt-1 text-xs text-ink-faint">
          資産・入出金の取込と、下の「生活状況」を入力すると、なぜ増えないかの診断と最善手が出ます。
        </p>
      </Panel>
    );
  }
  const lev = LEVERAGE[a.leverage] ?? LEVERAGE.none;
  return (
    <Panel>
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-ink">資産の最善手</h2>
        {a.debt > 0 && (
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${lev.cls}`}>{lev.label}</span>
        )}
      </div>

      {/* 看板: 総資産 × 純資産 */}
      <div className="mt-2 rounded-xl bg-void/40 p-3">
        <div className="text-[10px] uppercase tracking-wider text-ink-faint">看板指標 — 総資産 × 純資産を増やす</div>
        <div className="mt-1 flex items-baseline gap-2">
          <div>
            <div className="text-[10px] text-ink-faint">総資産</div>
            <div className="text-lg font-semibold tabular-nums text-ink">{yen(a.gross)}</div>
          </div>
          <span className="text-ink-faint">×</span>
          <div>
            <div className="text-[10px] text-ink-faint">純資産(=総資産−負債)</div>
            <div className={`text-lg font-semibold tabular-nums ${a.net < 0 ? "text-risk" : "text-ink"}`}>
              {yen(a.net)}
            </div>
          </div>
        </div>
        {lev.note && <div className={`mt-1 text-[10px] ${lev.cls}`}>{lev.note}</div>}
      </div>

      {/* 診断: なんで増えない */}
      {a.diagnosis.length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-dim">なんで増えない</div>
          <ul className="mt-1 space-y-1">
            {a.diagnosis.map((d) => (
              <li key={d.key} className="flex gap-1.5 text-[12px] text-ink-dim">
                <span className={d.level === "warn" ? "text-risk" : "text-ink-faint"}>
                  {d.level === "warn" ? "▲" : "・"}
                </span>
                <span className="min-w-0 flex-1">{d.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 最善手: 優先順位つき */}
      {a.moves.length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-dim">いまの最善手(優先順)</div>
          <ol className="mt-1 space-y-1.5">
            {a.moves.map((m, i) => (
              <li key={m.kind} className="flex gap-2 rounded-lg bg-void/30 p-2">
                <span className="text-[12px] font-bold text-act-300">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] font-medium text-ink">{m.text}</div>
                  <div className="text-[10px] text-ink-faint">{m.why}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </Panel>
  );
}

function NumField({ label, value, onChange, suffix }: {
  label: string; value: number | null; onChange: (v: number | null) => void; suffix?: string;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[10px] text-ink-faint">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          inputMode="decimal"
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          className="w-full rounded-lg border border-panel bg-void/50 px-2 py-1 text-[13px] tabular-nums text-ink"
        />
        {suffix && <span className="text-[10px] text-ink-faint">{suffix}</span>}
      </div>
    </label>
  );
}

/** 生活状況(世帯・住居・収入・負債・制度枠)。最善手の精度を上げる入力欄。 */
function LifeProfileForm({ data }: { data: FinanceResponse }) {
  const qc = useQueryClient();
  const mut = useFinanceMut(qc);
  const save = mut((v) => api.financeProfileSave(v as never));
  const [p, setP] = useState<FinanceResponse["profile"]>(data.profile);
  const set = <K extends keyof typeof p>(k: K, v: (typeof p)[K]) => setP((o) => ({ ...o, [k]: v }));

  return (
    <Panel>
      <h2 className="text-sm font-semibold text-ink">生活状況</h2>
      <p className="mt-0.5 text-[11px] text-ink-faint">
        資産データに出ない文脈(世帯・住居・負債・制度枠)を入れると、診断と最善手が具体的になります。
      </p>

      <div className="mt-2 space-y-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-dim">世帯</div>
          <div className="mt-1 grid grid-cols-3 gap-2">
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-ink-faint">配偶者</span>
              <button
                onClick={() => set("partner", !p.partner)}
                className={`rounded-lg px-2 py-1 text-[13px] ${p.partner ? "bg-prog-500/20 text-prog-300" : "bg-void/50 text-ink-dim"}`}
              >
                {p.partner ? "あり" : "なし"}
              </button>
            </label>
            <NumField label="子ども(人)" value={p.children} onChange={(v) => set("children", v)} />
            <NumField label="扶養(人)" value={p.dependents} onChange={(v) => set("dependents", v)} />
          </div>
        </div>

        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-dim">住居</div>
          <div className="mt-1 grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-ink-faint">形態</span>
              <select
                value={p.housing ?? ""}
                onChange={(e) => set("housing", (e.target.value || null) as typeof p.housing)}
                className="rounded-lg border border-panel bg-void/50 px-2 py-1 text-[13px] text-ink"
              >
                <option value="">—</option>
                <option value="rent">賃貸</option>
                <option value="own">持ち家</option>
              </select>
            </label>
            <NumField label="月の家賃/返済" value={p.housing_cost_jpy} onChange={(v) => set("housing_cost_jpy", v)} suffix="円" />
          </div>
        </div>

        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-dim">収入</div>
          <div className="mt-1 grid grid-cols-3 gap-2">
            <NumField label="手取り月収" value={p.monthly_income_jpy} onChange={(v) => set("monthly_income_jpy", v)} suffix="円" />
            <NumField label="月支出" value={p.monthly_expense_jpy} onChange={(v) => set("monthly_expense_jpy", v)} suffix="円" />
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-ink-faint">種類</span>
              <select
                value={p.income_type ?? ""}
                onChange={(e) => set("income_type", (e.target.value || null) as typeof p.income_type)}
                className="rounded-lg border border-panel bg-void/50 px-2 py-1 text-[13px] text-ink"
              >
                <option value="">—</option>
                <option value="employee">会社員</option>
                <option value="self_employed">自営</option>
                <option value="mixed">複合</option>
              </select>
            </label>
          </div>
        </div>

        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-dim">負債</div>
          <div className="mt-1 grid grid-cols-2 gap-2">
            <NumField label="残高" value={p.debt_balance_jpy} onChange={(v) => set("debt_balance_jpy", v)} suffix="円" />
            <NumField label="加重平均金利" value={p.debt_rate_pct} onChange={(v) => set("debt_rate_pct", v)} suffix="%" />
          </div>
        </div>

        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-dim">制度枠(月額)</div>
          <div className="mt-1 grid grid-cols-2 gap-2">
            <NumField label="NISA積立" value={p.nisa_monthly_jpy} onChange={(v) => set("nisa_monthly_jpy", v)} suffix="円" />
            <NumField label="iDeCo" value={p.ideco_monthly_jpy} onChange={(v) => set("ideco_monthly_jpy", v)} suffix="円" />
          </div>
        </div>

        <Button onClick={() => save.mutate(p)} disabled={save.isPending}>
          {save.isPending ? "保存中…" : "保存して診断を更新"}
        </Button>
      </div>
    </Panel>
  );
}

/** MoneyForward の任意スクショ(資産/負債/収支)を読み取り、重複除去+高確度のみ自動入力。 */
function MFScreenshotImport() {
  const qc = useQueryClient();
  const [summary, setSummary] = useState<FinanceResponse["import_summary"] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const mut = useMutation({
    mutationFn: (images: { image_base64: string; media_type: string }[]) =>
      api.financeImportScreenshots(images),
    onSuccess: (d) => {
      qc.setQueryData(["finance"], d);
      setSummary(d.import_summary ?? null);
      setErr(null);
    },
    onError: () => setErr("確度の高い項目を読み取れませんでした(未設定/読取不可の可能性)"),
  });
  return (
    <Panel>
      <h2 className="text-sm font-semibold text-ink">MoneyForward スクショ取込</h2>
      <p className="mt-0.5 text-[11px] text-ink-faint">
        資産・負債・月の収支・<strong className="text-ink-dim">予算(変動費の残り)</strong>、
        どの画面でもまとめて選択。中身を読み取り、重複を消し、
        <strong className="text-ink-dim">確度が高いものだけ</strong>自動で入れます(低いものは要確認で保留)。
        予算画面は「今日はいくらまで使っていいか」の日次目安にリアルタイムで反映されます。
      </p>
      <label className="mt-2 inline-block cursor-pointer rounded-lg bg-prog-700 px-3 py-1.5 text-xs text-void hover:bg-prog-500">
        {mut.isPending ? "読取中…" : "スクショを選ぶ(複数可)"}
        <input
          type="file" accept="image/*" multiple className="hidden"
          onChange={async (e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (!files.length) return;
            setSummary(null); setErr(null);
            const images = await Promise.all(
              files.map(async (f) => ({ image_base64: await fileToB64(f), media_type: f.type || "image/png" })),
            );
            mut.mutate(images);
          }}
        />
      </label>
      {err && <p className="mt-2 text-[11px] text-risk">{err}</p>}
      {summary && (
        <div className="mt-2 space-y-1 text-[11px]">
          <p className="text-prog-300">
            入りました — 資産{summary.entered.assets}件 / 負債{summary.entered.debts}件
            {summary.entered.income != null && ` / 月収入 ${yen(summary.entered.income)}`}
            {summary.entered.expense != null && ` / 月支出 ${yen(summary.entered.expense)}`}
            {summary.entered.budget != null &&
              ` / 予算残り ${yen(summary.entered.budget.remaining_jpy)}`
              + (summary.entered.budget.days_remaining != null
                ? `(あと${summary.entered.budget.days_remaining}日)` : "")}
          </p>
          {summary.entered.budget != null && (
            <p className="text-ink-faint">
              → 今日の「いまコレ」の衝動買い閾値がこの予算残りを元に計算されます。
            </p>
          )}
          {summary.skipped.length > 0 && (
            <div className="text-ink-faint">
              要確認(確度が低め・自動では入れていません):
              <ul className="mt-0.5 list-disc pl-4">
                {summary.skipped.map((s, i) => (
                  <li key={i}>
                    {s.type}
                    {s.name ? `「${s.name}」` : ""} {yen(s.value)}
                    {s.days_remaining != null && `・あと${s.days_remaining}日`}
                    （{s.confidence}）
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

export function FinancePage({ onBack }: { onBack: () => void }) {
  const q = useQuery({ queryKey: ["finance"], queryFn: api.finance, retry: false });
  const [roiOpen, setRoiOpen] = useState(false);
  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">← 戻る</button>
      <h1 className="text-xl font-bold text-ink">資産・投資</h1>
      <p className="text-xs text-ink-faint">
        総資産から防衛資金を引いた余剰を目標配分へ(リバランス)。貯蓄率がプラスに戻ったら、
        その余剰でROI上位の購入を検討。
      </p>
      {q.isError ? (
        <p className="text-sm text-risk">読み込みに失敗しました。少し待って再読み込みしてください。</p>
      ) : !q.data ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <AdvisorSection data={q.data} />
          <MFScreenshotImport />
          <CashflowSection data={q.data} />
          <RebalanceSection data={q.data} />
          <LifeProfileForm data={q.data} />
          {roiOpen ? (
            <RoiSection data={q.data} />
          ) : (
            <button
              onClick={() => setRoiOpen(true)}
              className="w-full rounded-card border border-white/[0.06] bg-hull p-3 text-left text-xs text-ink-faint hover:text-ink-dim"
            >
              ▶ 購入ROIランキング(mac mini Pro 等) — 今は使っていないので畳んでいます。タップで開く
            </button>
          )}
        </>
      )}
    </div>
  );
}

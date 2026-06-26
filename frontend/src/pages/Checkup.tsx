import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CheckupValue } from "../lib/api";
import { Button, Panel, Pill } from "../components/ui/cockpit";

const FLAG_TONE: Record<CheckupValue["flag"], "prog" | "risk" | "act" | "neutral"> = {
  normal: "prog",
  high: "risk",
  low: "act",
  unknown: "neutral",
};
const FLAG_LABEL: Record<CheckupValue["flag"], string> = {
  normal: "基準内",
  high: "高い",
  low: "低い",
  unknown: "—",
};

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export function CheckupPage({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["checkup"], queryFn: api.checkup });
  const [text, setText] = useState("");
  const upload = useMutation({
    mutationFn: (body: { text?: string; image_base64?: string; media_type?: string }) =>
      api.checkupUpload(body),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["checkup"] });
    },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.checkupDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["checkup"] }),
  });

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    const b64 = await fileToBase64(file);
    upload.mutate({ image_base64: b64, media_type: file.type || "image/png" });
  };

  const latest = q.data?.latest;
  const byCategory: Record<string, CheckupValue[]> = {};
  for (const v of latest?.values ?? []) (byCategory[v.category] ??= []).push(v);

  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold text-ink">健康診断</h1>
      <p className="text-xs text-ink-faint">
        結果を画像かテキストで取り込むと、科学的に有効な項目を抽出し基準値で判定します。判断材料として
        コーチングにも反映されます。
      </p>

      <Panel title="取り込む" glow="act">
        <div className="space-y-2">
          <label className="block">
            <span className="telemetry-label">画像から(写真・PDF画像)</span>
            <input
              type="file"
              accept="image/*"
              disabled={upload.isPending}
              onChange={(e) => onFile(e.target.files?.[0])}
              className="mt-1 block w-full text-xs text-ink-dim file:mr-2 file:rounded file:border-0 file:bg-act file:px-3 file:py-1 file:text-void"
            />
          </label>
          <span className="telemetry-label">またはテキストを貼り付け</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            placeholder="例: LDL 142 / HDL 58 / 中性脂肪 120 / HbA1c 5.4 / 血圧 128/82 ..."
            className="w-full rounded bg-panel px-2 py-1 text-sm text-ink"
          />
          <Button
            variant="primary"
            disabled={upload.isPending || !text.trim()}
            onClick={() => upload.mutate({ text })}
          >
            {upload.isPending ? "解析中…" : "テキストを取り込む"}
          </Button>
          {upload.isError && (
            <p className="text-xs text-risk">取り込みに失敗しました(読み取れない可能性)</p>
          )}
        </div>
      </Panel>

      {latest && (
        <Panel
          title={`最新の結果(${latest.date})`}
          action={
            <Button variant="ghost" onClick={() => del.mutate(latest.id)}>
              削除
            </Button>
          }
        >
          <p className="mb-2 text-sm text-ink-dim">{latest.summary}</p>
          <div className="space-y-3">
            {Object.entries(byCategory).map(([cat, vals]) => (
              <div key={cat}>
                <span className="telemetry-label">{cat}</span>
                <div className="mt-1 space-y-1">
                  {vals.map((v) => (
                    <div key={v.key} className="flex items-center justify-between text-sm">
                      <span className="text-ink-dim">{v.label}</span>
                      <span className="flex items-center gap-2">
                        <span className="telemetry-num text-ink">
                          {v.value}
                          <span className="ml-0.5 text-xs text-ink-faint">{v.unit}</span>
                        </span>
                        <Pill tone={FLAG_TONE[v.flag]}>{FLAG_LABEL[v.flag]}</Pill>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {q.data && q.data.history.length > 0 && (
        <Panel title="記録(実施日ごと)">
          <ul className="divide-y divide-hairline/60">
            {q.data.history.map((h) => (
              <li key={h.id} className="flex items-center justify-between py-1.5 text-sm">
                <span className="telemetry-num text-ink-dim">{h.date}</span>
                <button
                  disabled={del.isPending}
                  onClick={() => del.mutate(h.id)}
                  className="text-xs text-ink-faint hover:text-risk disabled:opacity-50"
                >
                  削除
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Button, Panel } from "../components/ui/cockpit";

const SCHEDULE_HOURS = [6, 9, 12, 15, 18, 21];

function weekdayJa(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return ["日", "月", "火", "水", "木", "金", "土"][d.getDay()] ?? "";
}

/**
 * 今日の紙(手書きジャーナルのテンプレ)。アプリの計算結果で“転記しやすく”埋める。
 * 書く行為は紙で(手書きは記憶・感情処理・コミットに効く)。アプリは候補提示に徹する。
 */
export function JournalPage({ onBack }: { onBack: () => void }) {
  const life = useQuery({ queryKey: ["life-tree"], queryFn: api.lifeTree });
  const today = useQuery({ queryKey: ["today"], queryFn: () => api.today(null), retry: false });
  const garden = useQuery({ queryKey: ["garden"], queryFn: api.garden, retry: false });
  const move = useMutation({ mutationFn: () => api.becomingOneMove() });
  const [copied, setCopied] = useState(false);

  const date = today.data?.date ?? "";
  const focusCapital = life.data?.capitals.find((c) => c.key === life.data?.focus_capital);
  const weakestName = garden.data?.weakest_hint?.name ?? null;
  const goalTitle = life.data?.goal?.title ?? null;
  const theme = weakestName
    ? `${weakestName} を伸ばす`
    : focusCapital
      ? `${focusCapital.label} に集中`
      : "—";
  const winning = move.data?.move ?? null;
  const condition = today.data?.score?.total ?? null;
  const alerts = (today.data?.alerts ?? []).filter((a) => a.severity !== "info");
  const breaches = (life.data?.capitals ?? []).filter((c) => c.breach).map((c) => c.label);

  const copyText = () => {
    const lines = [
      `# ${date}(${weekdayJa(date)})`,
      `## 感謝・話したこと・今日のテーマ`,
      `- 感謝する人: `,
      `- 話した人: `,
      `- テーマ: ${theme}${goalTitle ? `(${goalTitle} に向けて)` : ""}`,
      `## 今日これをやり切れば勝ちなタスク`,
      `- ${winning ?? ""}`,
      `## スケジュール`,
      ...SCHEDULE_HOURS.map((h) => `${h} `),
    ];
    navigator.clipboard?.writeText(lines.join("\n")).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">
        ← 戻る
      </button>
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-bold text-ink">今日の紙</h1>
        <Button variant="ghost" onClick={copyText}>
          {copied ? "コピーした" : "テキストでコピー"}
        </Button>
      </div>
      <p className="text-xs text-ink-faint">
        手書きノートに写して使ってください(手書きは記憶・感情処理・コミットに効く)。アプリは候補を出すだけ。
      </p>

      <Panel>
        <div className="space-y-4 font-mono text-sm leading-relaxed text-ink">
          <div className="text-base font-bold">
            {date}({weekdayJa(date)})
          </div>

          <div>
            <div className="text-ink-dim"># 感謝・話したこと・今日のテーマ</div>
            <div className="mt-1 space-y-0.5 text-ink-faint">
              <div>- 感謝する人: <span className="text-ink-faint/50">________</span></div>
              <div>- 話した人: <span className="text-ink-faint/50">________</span></div>
              <div>
                - テーマ: <span className="text-prog-300">{theme}</span>
                {goalTitle && <span className="text-ink-faint">(目標: {goalTitle})</span>}
              </div>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <span className="text-ink-dim"># 今日これをやり切れば勝ちなタスク</span>
              <Button
                variant="subtle"
                disabled={move.isPending}
                onClick={() => move.mutate()}
              >
                {move.isPending ? "生成中…" : winning ? "別の案" : "候補を出す"}
              </Button>
            </div>
            <div className="mt-1 text-act-300">
              - {winning ?? "(「候補を出す」で今日いちばん効く一手を提案)"}
            </div>
          </div>

          <div>
            <div className="text-ink-dim"># スケジュール(3時間枠 / ○=固定)</div>
            <div className="mt-1 space-y-0.5 text-ink-faint">
              {SCHEDULE_HOURS.map((h) => (
                <div key={h}>
                  {String(h).padStart(2, " ")} <span className="text-ink-faint/40">—</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Panel>

      {/* 守るべき線(アプリだけが計算できる:今日意識する制約)*/}
      {(breaches.length > 0 || alerts.length > 0 || condition !== null) && (
        <Panel title="今日 意識する線(アプリからの読み出し)">
          {condition !== null && (
            <p className="text-sm text-ink-dim">
              今日のコンディション <span className="telemetry-num text-prog-300">{Math.round(condition)}</span>
              {condition < 50 && <span className="ml-1 text-act-300">— 無理せず負荷を下げる</span>}
            </p>
          )}
          {alerts.map((a) => (
            <p key={a.code} className="mt-1 text-sm text-risk">
              ⚠ {a.title} — {a.action}
            </p>
          ))}
          {breaches.length > 0 && (
            <p className="mt-1 text-sm text-act-300">
              立て直す領域: {breaches.join(" / ")}
            </p>
          )}
        </Panel>
      )}
    </div>
  );
}

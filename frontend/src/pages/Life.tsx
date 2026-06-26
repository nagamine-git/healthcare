import { LifeTreePanel } from "../components/LifeTreePanel";

export function LifePage({ onBack }: { onBack: () => void }) {
  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold text-ink">人生 — 最適化ツリー</h1>
      <p className="text-xs text-ink-faint">
        目的 → 目標 → ドメイン → 行動。重点に寄せつつ、最低ラインは守る。
      </p>
      <LifeTreePanel />
    </div>
  );
}

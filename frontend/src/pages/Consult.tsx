import { ConsultChat } from "../components/ConsultChat";

/** AI コーチ。全データソースを踏まえて相談できる常設タブ。 */
export function ConsultPage() {
  return (
    <main className="safe-area-x pb-nav mx-auto max-w-3xl space-y-3">
      <header className="safe-area-top pb-0.5">
        <h1 className="app-title">相談</h1>
        <p className="mt-0.5 text-xs text-ink-faint">
          睡眠・栄養・運動・資産まで、あなたの全データを踏まえてAIが科学的に答えます。
        </p>
      </header>
      <ConsultChat />
    </main>
  );
}

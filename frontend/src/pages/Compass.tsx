import { useEffect, useState } from "react";
import { IdentityPage } from "./Identity";
import { LifePage } from "./Life";
import { BecomingPage } from "./Becoming";

const SEGMENTS = [
  { key: "values", label: "価値観・マインド" },
  { key: "purpose", label: "目的・領域" },
  { key: "path", label: "歩み・到達予測" },
] as const;
export type CompassSegment = (typeof SEGMENTS)[number]["key"];

/** 「自分の方向性」を1か所に統合した羅針盤。価値観/目的/歩み をセグメントで切替。 */
export function CompassPage({ initialSegment = "values" }: { initialSegment?: CompassSegment }) {
  const [seg, setSeg] = useState<CompassSegment>(initialSegment);
  useEffect(() => setSeg(initialSegment), [initialSegment]);
  const noop = () => {};

  return (
    <main className="safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <header className="safe-area-top pb-0.5">
        <h1 className="app-title">羅針盤</h1>
        <p className="mt-0.5 text-xs text-ink-faint">自分の方向性 — 価値観・目的・歩み</p>
      </header>

      <div className="sticky top-0 z-20 -mx-5 bg-void/75 px-5 py-2 backdrop-blur-xl">
        <div className="no-scrollbar flex gap-2 overflow-x-auto">
          {SEGMENTS.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => setSeg(s.key)}
              className={`press shrink-0 rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors ${
                seg === s.key ? "bg-ink text-void" : "bg-hull text-ink-dim hover:text-ink"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {seg === "values" && <IdentityPage onBack={noop} embedded />}
      {seg === "purpose" && <LifePage onBack={noop} embedded />}
      {seg === "path" && <BecomingPage onBack={noop} embedded />}
    </main>
  );
}

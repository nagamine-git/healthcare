import { useEffect, useState } from "react";

type Props = {
  lastUpdateIso: string | null | undefined;
  isRefreshing: boolean;
  onRefresh: () => void;
};

/**
 * データの最終更新時刻からの経過時間を監視し、滞っていれば警告バナーを表示する。
 *
 * Tier:
 * - < 30 分: 表示しない
 * - 30-60 分: amber (注意)
 * - 60-120 分: orange (警告)
 * - 120 分以上: rose (危険) "Garmin 同期が滞っています"
 */
export function StaleBanner({ lastUpdateIso, isRefreshing, onRefresh }: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  if (!lastUpdateIso) {
    return (
      <Banner
        tone="orange"
        message="最終更新時刻が不明です"
        hint="Garmin 連携を確認してください"
        isRefreshing={isRefreshing}
        onRefresh={onRefresh}
      />
    );
  }

  const ageMin = Math.floor((now - new Date(lastUpdateIso).getTime()) / 60_000);
  if (ageMin < 30) return null;

  let tone: "amber" | "orange" | "rose" = "amber";
  let message = `データが ${ageMin} 分前から更新されていません`;
  let hint: string | undefined;

  if (ageMin >= 120) {
    tone = "rose";
    message = `${Math.floor(ageMin / 60)} 時間以上 Garmin 同期が滞っています`;
    hint = "Garmin Connect への接続を確認し、再同期してください";
  } else if (ageMin >= 60) {
    tone = "orange";
    message = `データが ${ageMin} 分前から更新されていません`;
    hint = "自動更新が失敗している可能性があります";
  }

  return (
    <Banner
      tone={tone}
      message={message}
      hint={hint}
      isRefreshing={isRefreshing}
      onRefresh={onRefresh}
    />
  );
}

function Banner({
  tone,
  message,
  hint,
  isRefreshing,
  onRefresh,
}: {
  tone: "amber" | "orange" | "rose";
  message: string;
  hint?: string;
  isRefreshing: boolean;
  onRefresh: () => void;
}) {
  const style =
    tone === "rose"
      ? "border-rose-700/70 bg-rose-900/30 text-rose-100"
      : tone === "orange"
      ? "border-orange-700/60 bg-orange-900/25 text-orange-200"
      : "border-amber-700/50 bg-amber-900/20 text-amber-200";
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-2 ${style}`}
    >
      <div className="flex-1 min-w-0">
        <div className="text-sm">{message}</div>
        {hint && <div className="text-[11px] opacity-80">{hint}</div>}
      </div>
      <button
        onClick={onRefresh}
        disabled={isRefreshing}
        className="rounded-full border border-current/40 bg-current/10 px-3 py-1 text-xs hover:bg-current/20 disabled:opacity-40"
      >
        {isRefreshing ? "更新中..." : "今すぐ更新"}
      </button>
    </div>
  );
}

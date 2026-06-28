import type { TargetRange } from "../lib/api";

type Props = {
  current: number | null;
  target: TargetRange;
  /** バー満杯にする値。指定しなければ max ?? ideal*1.2 ?? current */
  scaleMax?: number;
};

/** 現状値と目標範囲を 1 本のバーで示す。
 *  - kind=range: min-max 帯を緑、外側を warn 色
 *  - kind=minimum: ideal 以上を緑、未達を warn
 *  - kind=exact: ideal 一点に近いほど緑
 *  - kind=baseline_relative: ベースライン基準(±σ等)、絶対値は描かない
 */
export function RangeBar({ current, target, scaleMax }: Props) {
  if (target.kind === "baseline_relative") {
    return null;
  }
  const max =
    scaleMax ??
    target.max ??
    (target.ideal ? target.ideal * 1.4 : current ? current * 1.4 : 100);
  const cur = current ?? 0;
  const pct = (v: number) => Math.max(0, Math.min(100, (v / max) * 100));

  const minPct = target.min != null ? pct(target.min) : null;
  const idealPct = target.ideal != null ? pct(target.ideal) : null;
  const maxPct = target.max != null ? pct(target.max) : null;
  const curPct = pct(cur);

  // 評価: 範囲内なら ok、範囲外なら warn (高 or 低)
  const inRange =
    target.kind === "range"
      ? (target.min == null || cur >= target.min) && (target.max == null || cur <= target.max)
      : target.kind === "minimum"
      ? target.ideal == null || cur >= target.ideal
      : target.ideal == null || Math.abs(cur - target.ideal) / target.ideal < 0.1;

  const fillColor = current == null ? "#475569" : inRange ? "#34d399" : "#f59e0b";
  const overColor = "#fb7185"; // 範囲を大きく超えた場合
  const farOver =
    target.kind === "range" && target.max != null && cur > target.max * 1.2;
  const finalColor = farOver ? overColor : fillColor;

  return (
    <div className="relative h-2 w-full overflow-hidden rounded-full bg-panel">
      {/* 推奨範囲帯 (うっすら緑) */}
      {minPct != null && maxPct != null && (
        <div
          className="absolute h-full bg-prog-900/30"
          style={{ left: `${minPct}%`, width: `${maxPct - minPct}%` }}
        />
      )}
      {/* 現状の塗り */}
      <div
        className="absolute h-full transition-all"
        style={{ width: `${curPct}%`, background: finalColor }}
      />
      {/* min マーカー */}
      {minPct != null && (
        <div
          className="absolute top-0 h-full w-px bg-ink-faint"
          style={{ left: `${minPct}%` }}
        />
      )}
      {/* ideal マーカー (太め) */}
      {idealPct != null && (
        <div
          className="absolute top-0 h-full w-0.5 bg-ink-dim"
          style={{ left: `${idealPct}%` }}
        />
      )}
      {/* max マーカー */}
      {maxPct != null && (
        <div
          className="absolute top-0 h-full w-px bg-ink-faint"
          style={{ left: `${maxPct}%` }}
        />
      )}
    </div>
  );
}

/** "現状 / min – ideal – max unit" のテキスト表示 */
export function formatRange(
  current: number | null,
  target: TargetRange,
  digits = 0,
): string {
  const fmt = (v: number | null | undefined) =>
    v == null ? "—" : digits > 0 ? v.toFixed(digits) : Math.round(v).toString();
  const u = target.unit;
  if (target.kind === "minimum") {
    return `${fmt(current)} / 目標 ${fmt(target.ideal)}+ ${u}`;
  }
  if (target.kind === "exact") {
    return `${fmt(current)} / 目標 ${fmt(target.ideal)} ${u}`;
  }
  if (target.kind === "range") {
    if (target.min != null && target.max != null) {
      return `${fmt(current)} / 推奨 ${fmt(target.min)}–${fmt(target.max)} ${u}`;
    }
    return `${fmt(current)} / 目標 ${fmt(target.ideal)} ${u}`;
  }
  return `${fmt(current)} ${u}`;
}

import { EVIDENCE_LABEL, weightAt, weightForBmi, zonesFor } from "../lib/bodyCompZones";
import type { Zone } from "../lib/bodyCompZones";

/**
 * 体組成マップ: X=体重 / Y=体脂肪率 の平面に、目的別ゾーン (健康/体力/実用/魅力) を
 * 半透明で重ねる。現在地と目標地点をマーカーで表示。温湿度の快適域チャートの体組成版。
 */

const W = 320;
const H = 220;
const PAD = { l: 30, r: 8, t: 8, b: 22 };

export function BodyCompositionMap({
  heightCm,
  sex,
  current,
  target,
}: {
  heightCm: number;
  sex: "male" | "female";
  current?: { weight: number; bf: number } | null;
  target?: { weight: number; bf: number } | null;
}) {
  // 軸レンジ: 体重 = BMI 16–27、体脂肪 = 性別で 5–28 / 11–34
  const wMin = weightForBmi(heightCm, 16);
  const wMax = weightForBmi(heightCm, 27);
  const bfMin = sex === "female" ? 11 : 5;
  const bfMax = sex === "female" ? 34 : 28;

  const x = (w: number) => PAD.l + ((w - wMin) / (wMax - wMin)) * (W - PAD.l - PAD.r);
  const y = (bf: number) => PAD.t + ((bf - bfMin) / (bfMax - bfMin)) * (H - PAD.t - PAD.b);

  const zones = zonesFor(sex);

  function zonePath(z: Zone): string {
    const steps = 16;
    const left: [number, number][] = [];
    const right: [number, number][] = [];
    for (let i = 0; i <= steps; i++) {
      const bf = z.bf[0] + ((z.bf[1] - z.bf[0]) * i) / steps;
      let wl: number, wr: number;
      if (z.kind === "bmi") {
        wl = weightForBmi(heightCm, z.bmi[0]);
        wr = weightForBmi(heightCm, z.bmi[1]);
      } else {
        wl = weightAt(heightCm, bf, z.ffmi[0]);
        wr = weightAt(heightCm, bf, z.ffmi[1]);
      }
      left.push([x(wl), y(bf)]);
      right.push([x(wr), y(bf)]);
    }
    const pts = [...left, ...right.reverse()];
    return "M " + pts.map(([px, py]) => `${px.toFixed(1)} ${py.toFixed(1)}`).join(" L ") + " Z";
  }

  // 軸目盛
  const wTicks: number[] = [];
  for (let bmi = 16; bmi <= 27; bmi += 2) wTicks.push(Math.round(weightForBmi(heightCm, bmi)));
  const bfTicks = sex === "female" ? [12, 18, 24, 30] : [6, 12, 18, 24];

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="体組成マップ">
        {/* グリッド + 軸 */}
        {wTicks.map((w) => (
          <g key={`wx${w}`}>
            <line x1={x(w)} y1={PAD.t} x2={x(w)} y2={H - PAD.b} stroke="#1e293b" strokeWidth={1} />
            <text x={x(w)} y={H - PAD.b + 12} fontSize={8} fill="#64748b" textAnchor="middle">{w}</text>
          </g>
        ))}
        {bfTicks.map((bf) => (
          <g key={`by${bf}`}>
            <line x1={PAD.l} y1={y(bf)} x2={W - PAD.r} y2={y(bf)} stroke="#1e293b" strokeWidth={1} />
            <text x={PAD.l - 3} y={y(bf) + 3} fontSize={8} fill="#64748b" textAnchor="end">{bf}%</text>
          </g>
        ))}
        <text x={W - PAD.r} y={H - PAD.b + 12} fontSize={8} fill="#475569" textAnchor="end">体重kg →</text>

        {/* ゾーン */}
        {zones.map((z) => (
          <path key={z.key} d={zonePath(z)} fill={z.fill} stroke={z.stroke} strokeWidth={1}
                strokeDasharray={z.evidence === "weak" ? "3 2" : undefined} />
        ))}

        {/* 現在地 */}
        {current && current.bf != null && current.weight != null && (
          <g>
            <circle cx={x(current.weight)} cy={y(current.bf)} r={4} fill="#f8fafc" stroke="#0f172a" strokeWidth={1.5} />
            <text x={x(current.weight) + 6} y={y(current.bf) - 5} fontSize={8} fill="#f8fafc">現在</text>
          </g>
        )}
        {/* 目標地 */}
        {target && (
          <g>
            <circle cx={x(target.weight)} cy={y(target.bf)} r={4.5} fill="#34d399" stroke="#022c22" strokeWidth={1.5} />
            <text x={x(target.weight) + 6} y={y(target.bf) + 10} fontSize={8} fill="#6ee7b7">目標</text>
          </g>
        )}
      </svg>

      {/* 凡例 */}
      <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1">
        {zones.map((z) => (
          <div key={z.key} className="flex items-start gap-1.5 text-[9px] leading-tight">
            <span className="mt-0.5 h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: z.fill, border: `1px solid ${z.stroke}` }} />
            <span>
              <span className="text-ink-dim">{z.label}</span>
              <span className="text-ink-faint"> · {EVIDENCE_LABEL[z.evidence]}</span>
              <span className="block text-ink-faint">{z.source}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

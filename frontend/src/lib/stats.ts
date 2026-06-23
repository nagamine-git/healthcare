/** 統計の純粋関数。 */

/** 正規分布の確率密度。分布曲線の描画に使う。 */
export function normalPdf(x: number, mean: number, sd: number): number {
  if (sd <= 0) return 0;
  const z = (x - mean) / sd;
  return Math.exp(-0.5 * z * z) / (sd * Math.sqrt(2 * Math.PI));
}

/** mean±3sd を n 点サンプリングした (x, 密度) 列。ベルカーブ描画用。 */
export function bellCurve(
  mean: number,
  sd: number,
  n = 41,
): Array<{ x: number; y: number }> {
  const lo = mean - 3 * sd;
  const hi = mean + 3 * sd;
  const step = (hi - lo) / (n - 1);
  return Array.from({ length: n }, (_, i) => {
    const x = lo + step * i;
    return { x, y: normalPdf(x, mean, sd) };
  });
}

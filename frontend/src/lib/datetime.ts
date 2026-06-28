/**
 * datetime-local input (YYYY-MM-DDTHH:MM、タイムゾーン無し) を JST aware の
 * ISO 文字列に変換する。アプリは JST シングルユーザー前提なので +09:00 固定。
 */
export function localToJstIso(localValue: string): string | undefined {
  if (!localValue) return undefined;
  // 秒省略形なら :00 を足す
  const withSec = localValue.length === 16 ? `${localValue}:00` : localValue;
  return `${withSec}+09:00`;
}


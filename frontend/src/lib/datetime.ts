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

/**
 * 現在時刻を datetime-local の value 形式 (YYYY-MM-DDTHH:MM、JST 暦) で返す。
 */
export function nowAsLocalValue(): string {
  const now = new Date();
  // JST に固定 (Asia/Tokyo)
  const fmt = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  // sv-SE は YYYY-MM-DD HH:MM 形式で返す
  const s = fmt.format(now);
  return s.replace(" ", "T");
}

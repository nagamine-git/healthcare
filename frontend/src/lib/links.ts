/** 推薦作品の外部リンク。IMDb があればそれ、無ければ Google 検索にフォールバック。 */
export function mediaLink(item: {
  title: string;
  year?: number | null;
  kind?: string;
  imdb_url?: string | null;
}): { href: string; label: string; isImdb: boolean } {
  if (item.imdb_url) return { href: item.imdb_url, label: "IMDb", isImdb: true };
  const term =
    item.kind === "book"
      ? " 本"
      : item.kind === "manga"
        ? " 漫画"
        : item.kind === "tv"
          ? " ドラマ"
          : item.kind === "film"
            ? " 映画"
            : "";
  const q = `${item.title}${item.year ? ` ${item.year}` : ""}${term}`;
  return {
    href: `https://www.google.com/search?q=${encodeURIComponent(q)}`,
    label: "Google",
    isImdb: false,
  };
}

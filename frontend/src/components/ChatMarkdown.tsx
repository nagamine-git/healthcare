import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

/**
 * 口頭試問・復習チャットの assistant 発話を Markdown レンダリングする。
 *
 * Tailwind typography プラグインは未導入のため、ダークテーマに合わせて要素ごとに
 * クラスを当てる。インラインコード / コードブロック / 箇条書き / 表などに対応。
 */

const components: Components = {
  p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-slate-50">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-amber-300 underline underline-offset-2">
      {children}
    </a>
  ),
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  h1: ({ children }) => <h1 className="mb-1 mt-2 text-[15px] font-semibold text-slate-50">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-1 mt-2 text-[14px] font-semibold text-slate-50">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 mt-2 text-[13px] font-semibold text-slate-100">{children}</h3>,
  blockquote: ({ children }) => (
    <blockquote className="my-1.5 border-l-2 border-slate-600 pl-2.5 text-slate-400">{children}</blockquote>
  ),
  hr: () => <hr className="my-2 border-slate-700" />,
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-slate-950/70 p-2.5 text-[12px] leading-relaxed">
      {children}
    </pre>
  ),
  code: ({ className, children }) => {
    // fenced code block は className (language-xxx) を持つ。インラインはそれ以外。
    const isBlock = Boolean(className);
    if (isBlock) {
      return <code className={`${className} font-mono text-slate-100`}>{children}</code>;
    }
    return (
      <code className="rounded bg-slate-950/60 px-1 py-0.5 font-mono text-[12px] text-amber-200">
        {children}
      </code>
    );
  },
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-[12px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-slate-700 bg-slate-800/60 px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border border-slate-700 px-2 py-1">{children}</td>,
};

export function ChatMarkdown({ content }: { content: string }) {
  return (
    <div className="text-[13px] leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * The assistant's answer, formatted.
 *
 * It used to render inside a single <p> with whitespace-pre-wrap, so every
 * `##`, `**` and `- ` the model writes appeared literally — the answer read
 * like source code. react-markdown does not render raw HTML unless asked, so
 * nothing here needs a separate sanitizer.
 *
 * No typography plugin: every element carries the brand tokens explicitly,
 * which is how the rest of this codebase styles text.
 */

/** Turn the model's `[3]` into a real link so markdown itself parses it.
 *
 * Doing it this way rather than walking the rendered tree keeps citations
 * working inside bold text, list items and table cells, which is exactly
 * where they appear. A `[3]` already followed by `(` is left alone — that is
 * a link the model wrote on purpose. */
const linkCitations = (md: string) =>
  md.replace(/\[(\d+)\](?!\()/g, (_m, n) => `[${n}](#fonte-${n})`);

export function AnswerBody({
  content,
  onCite,
}: {
  content: string;
  onCite?: (n: number) => void;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // The answer already lives inside a card, so a document-level title
        // would compete with the page's own heading.
        h1: ({ children }) => (
          <h3 className="mt-4 mb-2 text-base font-bold text-heading first:mt-0">{children}</h3>
        ),
        h2: ({ children }) => (
          <h3 className="mt-4 mb-2 text-base font-bold text-heading first:mt-0">{children}</h3>
        ),
        h3: ({ children }) => (
          <h4 className="mt-3 mb-1.5 text-sm font-bold text-navy first:mt-0">{children}</h4>
        ),
        p: ({ children }) => (
          <p className="mb-3 text-sm leading-relaxed text-navy last:mb-0">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="mb-3 flex list-disc flex-col gap-1.5 pl-5 last:mb-0">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-3 flex list-decimal flex-col gap-1.5 pl-5 last:mb-0">{children}</ol>
        ),
        li: ({ children }) => (
          <li className="text-sm leading-relaxed text-navy marker:text-secondary/60">
            {children}
          </li>
        ),
        strong: ({ children }) => (
          <strong className="font-bold text-heading">{children}</strong>
        ),
        em: ({ children }) => <em className="italic text-navy/90">{children}</em>,
        code: ({ children }) => (
          <code className="rounded bg-surface px-1.5 py-0.5 text-xs text-heading">
            {children}
          </code>
        ),
        blockquote: ({ children }) => (
          <blockquote className="mb-3 border-l-2 border-secondary/40 pl-3 text-sm italic text-muted last:mb-0">
            {children}
          </blockquote>
        ),
        hr: () => <hr className="my-4 border-border" />,
        // Wide tables scroll inside their own box: the page must never
        // scroll sideways on a phone.
        table: ({ children }) => (
          <div className="mb-3 overflow-x-auto rounded-xl border border-border last:mb-0">
            <table className="w-full text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-surface text-left text-xs font-bold uppercase tracking-wider text-muted">
            {children}
          </thead>
        ),
        tbody: ({ children }) => (
          <tbody className="divide-y divide-border">{children}</tbody>
        ),
        th: ({ children }) => <th className="px-3 py-2">{children}</th>,
        td: ({ children }) => <td className="px-3 py-2 align-top text-navy">{children}</td>,
        a: ({ href, children }) => {
          const cite = href?.match(/^#fonte-(\d+)$/);
          if (cite) {
            const n = Number(cite[1]);
            return (
              <button
                type="button"
                onClick={() => onCite?.(n)}
                aria-label={`Vai alla fonte ${n}`}
                className="mx-0.5 inline-flex min-h-5 items-center rounded-md bg-secondary/10 px-1.5
                           align-baseline text-xs font-bold text-secondary transition duration-200
                           hover:bg-secondary/20 focus-visible:outline focus-visible:outline-2
                           focus-visible:outline-offset-1 focus-visible:outline-secondary"
              >
                {children}
              </button>
            );
          }
          return (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="font-semibold text-secondary underline underline-offset-2 hover:text-heading"
            >
              {children}
            </a>
          );
        },
      }}
    >
      {linkCitations(content)}
    </ReactMarkdown>
  );
}

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { askKnowledge, type AskResult, type KnowledgeHit } from "../api/knowledge";
import { Badge, Button, fieldCls } from "../components/ui/primitives";
import { PageTransition, EASE } from "../components/ui/motion";
import { AnswerBody } from "../components/knowledge/AnswerBody";

type Scope = "all" | "medyca" | "competitor";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: KnowledgeHit[];
  model?: string;
  /** Pages read for this turn, and any that could not be. */
  refs?: string[];
  refProblems?: { url: string; error: string }[];
}

/** Links written in the message itself.
 *
 * No separate field for this: someone asking "look at this page and tell me
 * what we are missing" pastes the link into the sentence, and a second box
 * would be a rule to remember rather than a feature. */
const URL_RE = /https?:\/\/[^\s<>"')]+/gi;
const findUrls = (text: string) =>
  Array.from(new Set(text.match(URL_RE) ?? [])).slice(0, 3);

const hostOf = (u: string) => {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
};

/**
 * A chat over everything the platform knows — Medyca's own reels and articles
 * plus the competitors'. Answers are built only from retrieved sources and
 * carry their citations, so the client can check a claim instead of trusting
 * it. Every source states whose content it is: confusing what Medyca said with
 * what a competitor said would be the worst failure this screen could make.
 */
export default function KnowledgeBank() {
  const { t } = useTranslation();
  const [scope, setScope] = useState<Scope>("all");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [elapsed, setElapsed] = useState(0);
  // Which citation the reader just clicked, so the matching source can be
  // scrolled to and highlighted. Inert [n] text was the old behaviour.
  const [focus, setFocus] = useState<{ msg: number; n: number } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const ask = useMutation<AskResult, unknown, string>({
    mutationFn: (query) =>
      askKnowledge(query, {
        scope,
        history: messages.slice(-6).map((m) => ({ role: m.role, content: m.content })),
        references: findUrls(query),
      }),
    onSuccess: (data) =>
      setMessages((m) => [
        ...m,
        {
          role: "assistant", content: data.answer, sources: data.sources,
          model: data.model, refProblems: data.reference_problems,
        },
      ]),
    onError: () =>
      setMessages((m) => [...m, { role: "assistant", content: t("common.error") }]),
  });

  // A reply takes ~30s and does not stream; a running counter is the honest
  // way to show it is working rather than a bar that cannot move.
  useEffect(() => {
    if (!ask.isPending) {
      setElapsed(0);
      return;
    }
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [ask.isPending]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, ask.isPending]);

  const focusSource = (msg: number, n: number) => {
    setFocus({ msg, n });
    document.getElementById(`fonte-${msg}-${n}`)?.scrollIntoView({
      behavior: "smooth", block: "center",
    });
  };

  const send = (text: string) => {
    const q = text.trim();
    if (q.length < 3 || ask.isPending) return;
    setMessages((m) => [...m, { role: "user", content: q, refs: findUrls(q) }]);
    setInput("");
    ask.mutate(q);
  };

  const suggestions = t("kb.suggestions", { returnObjects: true }) as string[];

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="flex flex-col gap-3 border-b border-border px-4 pb-4 pt-5 sm:flex-row sm:items-end sm:justify-between sm:px-6">
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-heading">{t("kb.chatTitle")}</h1>
            <p className="text-sm text-muted">{t("kb.chatSubtitle")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-full border border-border bg-white p-1">
              {(["all", "medyca", "competitor"] as Scope[]).map((s) => (
                <button
                  key={s}
                  onClick={() => setScope(s)}
                  className={
                    "rounded-full px-3 py-1 text-xs font-bold transition " +
                    (scope === s
                      ? s === "competitor"
                        ? "bg-warning/10 text-warning"
                        : "bg-secondary/10 text-secondary"
                      : "text-muted hover:text-navy")
                  }
                >
                  {t(
                    s === "all"
                      ? "kb.scopeAll"
                      : s === "medyca"
                        ? "kb.scopeMedyca"
                        : "kb.scopeCompetitor"
                  )}
                </button>
              ))}
            </div>
            {messages.length > 0 && (
              <Button variant="ghost" onClick={() => setMessages([])}>
                {t("kb.clear")}
              </Button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {messages.length === 0 && !ask.isPending && (
              <div className="rounded-2xl border border-border bg-surface p-5 shadow-card">
                <p className="mb-3 text-sm font-bold text-navy">{t("kb.suggest")}</p>
                <div className="flex flex-col gap-2">
                  {suggestions.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="rounded-xl border border-border bg-white px-4 py-2.5 text-left text-sm text-navy transition hover:border-secondary hover:shadow-card"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.24, ease: EASE }}
                className={m.role === "user" ? "flex justify-end" : ""}
              >
                {m.role === "user" ? (
                  <div className="flex max-w-[85%] flex-col items-end gap-1.5">
                    <div className="rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-sm font-medium text-white">
                      {m.content}
                    </div>
                    {/* Say which pages are being read. A link in the sentence
                        silently changing what the answer draws on would be a
                        surprise, and the point here is knowing the source. */}
                    {m.refs && m.refs.length > 0 && (
                      <div className="flex flex-wrap justify-end gap-1.5">
                        {m.refs.map((u) => (
                          <Badge key={u} className="bg-warning/10 text-warning">
                            {t("kb.reading_page")} {hostOf(u)}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    <div className="rounded-2xl rounded-bl-md border border-border bg-white p-4 shadow-card">
                      <AnswerBody content={m.content} onCite={(n) => focusSource(i, n)} />
                    </div>
                    {m.refProblems && m.refProblems.length > 0 && (
                      <div className="rounded-xl border border-danger/30 bg-danger/5 p-3">
                        {m.refProblems.map((p) => (
                          <p key={p.url} className="text-xs text-danger">
                            <span className="font-semibold">{hostOf(p.url)}</span> — {p.error}
                          </p>
                        ))}
                      </div>
                    )}
                    {m.sources && m.sources.length > 0 && (
                      <Sources hits={m.sources} model={m.model} msgIndex={i}
                               focused={focus?.msg === i ? focus.n : null} />
                    )}
                  </div>
                )}
              </motion.div>
            ))}

            {ask.isPending && (
              <div className="flex items-center gap-3 rounded-2xl rounded-bl-md border border-border bg-white p-4 shadow-card">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-secondary" />
                <span className="text-sm text-muted">
                  {t("kb.reading")} {elapsed > 3 ? `(${elapsed}s)` : ""}
                </span>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="border-t border-border bg-white/85 px-4 py-3 backdrop-blur sm:px-6">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="mx-auto flex max-w-3xl items-center gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t("kb.placeholder")}
              className={fieldCls + " h-12 min-w-0 flex-1 rounded-2xl text-base"}
            />
            <Button
              type="submit"
              disabled={input.trim().length < 3}
              loading={ask.isPending}
              className="h-12 shrink-0"
            >
              {t("kb.send")}
            </Button>
          </form>
        </div>
      </div>
    </PageTransition>
  );
}

/** Origin decides the colour, and grouping makes the comparison visible:
 *  the whole product rests on never confusing Medyca's material with the
 *  competitors'. Blue is Medyca and amber the competition, the same coding
 *  ScopeBadge and the constellation map already use. */
const originOf = (h: KnowledgeHit) =>
  h.owner === "external" ? "external" : h.owner === "competitor" ? "competitor" : "owned";

const ORIGINS = ["external", "owned", "competitor"] as const;

function Sources({ hits, model, msgIndex, focused }: {
  hits: KnowledgeHit[]; model?: string; msgIndex: number; focused: number | null;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border border-border bg-surface p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-muted">
        {t("kb.sources")}
        {model && <Badge className="bg-white normal-case text-muted">🤖 {model}</Badge>}
      </div>
      <div className="flex flex-col gap-3">
        {ORIGINS.map((origin) => {
          const group = hits
            .map((h, i) => ({ h, n: i + 1 }))
            .filter(({ h }) => originOf(h) === origin);
          if (!group.length) return null;
          return (
            <div key={origin} className="flex flex-col gap-1.5">
              <div className="text-[10px] font-bold uppercase tracking-wider text-muted/70">
                {t(`kb.origin.${origin}`)} · {group.length}
              </div>
              {group.map(({ h, n }) => {
          const i = n - 1;
          const comp = h.owner === "competitor";
          // A pasted page is not Medyca's material and must never be dressed
          // as it: mistaking someone else's content for our own is the worst
          // failure this screen can make.
          const ext = h.owner === "external";
          return (
            <a
              key={`${h.kind}-${h.id}-${n}`}
              id={`fonte-${msgIndex}-${n}`}
              href={h.url}
              target="_blank"
              rel="noreferrer"
              className={
                "flex items-start gap-2 rounded-xl border bg-white px-3 py-2 text-xs transition duration-200 hover:shadow-card " +
                (focused === n
                  ? "border-secondary ring-2 ring-secondary/30"
                  : h.cited
                    ? "border-secondary/40"
                    : "border-border")
              }
            >
              <span className="font-bold text-muted">[{n}]</span>
              <span className="min-w-0 flex-1">
                <span className="line-clamp-1 font-semibold text-navy">
                  {h.title.replace(/ — Medyca$/, "").trim() ||
                    h.snippet?.slice(0, 60) ||
                    t("kb.untitled")}
                </span>
                <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                  <Badge
                    className={
                      ext
                        ? "bg-heading/10 text-heading"
                        : comp
                          ? "bg-warning/10 text-warning"
                          : "bg-secondary/10 text-secondary"
                    }
                  >
                    {ext
                      ? t("kb.externalRef")
                      : comp
                        ? `competitor${h.account ? " @" + h.account : ""}`
                        : "Medyca"}
                  </Badge>
                  <span className="text-muted/80">
                    {ext
                      ? hostOf(h.url)
                      : h.kind === "blog"
                        ? "articolo"
                        : "reel"}{" "}
                    · {(h.score * 100).toFixed(0)}%
                  </span>
                </span>
              </span>
            </a>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

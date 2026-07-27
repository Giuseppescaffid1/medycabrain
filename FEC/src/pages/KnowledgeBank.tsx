import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { askKnowledge, type AskResult, type KnowledgeHit } from "../api/knowledge";
import { Badge, Button, fieldCls } from "../components/ui/primitives";
import { PageTransition, EASE } from "../components/ui/motion";

type Scope = "all" | "medyca" | "competitor";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: KnowledgeHit[];
  model?: string;
}

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
  const endRef = useRef<HTMLDivElement>(null);

  const ask = useMutation<AskResult, unknown, string>({
    mutationFn: (query) =>
      askKnowledge(query, {
        scope,
        history: messages.slice(-6).map((m) => ({ role: m.role, content: m.content })),
      }),
    onSuccess: (data) =>
      setMessages((m) => [
        ...m,
        { role: "assistant", content: data.answer, sources: data.sources, model: data.model },
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

  const send = (text: string) => {
    const q = text.trim();
    if (q.length < 3 || ask.isPending) return;
    setMessages((m) => [...m, { role: "user", content: q }]);
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
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-sm font-medium text-white">
                    {m.content}
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    <div className="rounded-2xl rounded-bl-md border border-border bg-white p-4 shadow-card">
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-navy">
                        {m.content}
                      </p>
                    </div>
                    {m.sources && m.sources.length > 0 && (
                      <Sources hits={m.sources} model={m.model} />
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

function Sources({ hits, model }: { hits: KnowledgeHit[]; model?: string }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border border-border bg-surface p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-muted">
        {t("kb.sources")}
        {model && <Badge className="bg-white normal-case text-muted">🤖 {model}</Badge>}
      </div>
      <div className="flex flex-col gap-1.5">
        {hits.map((h, i) => {
          const comp = h.owner === "competitor";
          return (
            <a
              key={`${h.kind}-${h.id}`}
              href={h.url}
              target="_blank"
              rel="noreferrer"
              className={
                "flex items-start gap-2 rounded-xl border bg-white px-3 py-2 text-xs transition hover:shadow-card " +
                (h.cited ? "border-secondary/40" : "border-border")
              }
            >
              <span className="font-bold text-muted">[{i + 1}]</span>
              <span className="min-w-0 flex-1">
                <span className="line-clamp-1 font-semibold text-navy">
                  {h.title.replace(/ — Medyca$/, "")}
                </span>
                <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                  <Badge
                    className={comp ? "bg-warning/10 text-warning" : "bg-secondary/10 text-secondary"}
                  >
                    {comp ? `competitor${h.account ? " @" + h.account : ""}` : "Medyca"}
                  </Badge>
                  <span className="text-muted/80">
                    {h.kind === "blog" ? "articolo" : "reel"} · {(h.score * 100).toFixed(0)}%
                  </span>
                </span>
              </span>
            </a>
          );
        })}
      </div>
    </div>
  );
}

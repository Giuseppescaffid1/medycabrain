import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import { fetchKnowledgeDoc, type KnowledgeDocDetail } from "../../api/knowledge";
import { Badge, Spinner } from "../ui/primitives";
import { AnswerBody } from "../knowledge/AnswerBody";
import { formatDate } from "../../lib/utils";

/**
 * The article twin of ReelDetailDrawer — same shell, same gestures.
 *
 * What a reel drawer has that makes no sense here is simply absent:
 * no transcript (the body IS the text), no STT quality bar, no annotations.
 * The body renders through the same markdown renderer as the chat, so the
 * whole product formats prose exactly one way.
 */
export function ArticleDetailDrawer({
  docId,
  onClose,
}: {
  docId: number | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { data: doc, isLoading } = useQuery({
    queryKey: ["knowledge-doc", docId],
    queryFn: () => fetchKnowledgeDoc(docId!),
    enabled: docId != null,
  });

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onClose]);

  return (
    <AnimatePresence>
      {docId != null && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-navy/30"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            className="fixed right-0 top-0 z-50 flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-border bg-white shadow-float"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "tween", duration: 0.25 }}
          >
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-white/85 px-5 py-3 backdrop-blur">
              <span className="truncate text-sm font-semibold text-muted">
                {doc?.source?.name ?? ""}
              </span>
              <button
                onClick={onClose}
                className="shrink-0 rounded-full px-3 py-1.5 text-sm font-semibold text-muted transition hover:bg-surface hover:text-navy"
              >
                ✕ {t("common.close")}
              </button>
            </div>

            {isLoading || !doc ? (
              <Spinner label={t("common.loading")} />
            ) : (
              <Body doc={doc} />
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function Body({ doc }: { doc: KnowledgeDocDetail }) {
  const { t } = useTranslation();
  const comp = doc.owner_type === "competitor";

  return (
    <div className="flex flex-col gap-5 p-5">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge className={comp ? "bg-warning/10 text-warning" : "bg-secondary/10 text-secondary"}>
            {doc.source?.name || "Medyca"}
          </Badge>
          {doc.primary_topic && (
            <Badge className="bg-surface text-heading">{doc.primary_topic}</Badge>
          )}
          {doc.language && doc.language !== "it" && (
            <Badge className="bg-surface text-muted uppercase">{doc.language}</Badge>
          )}
        </div>
        <h2 className="text-lg font-bold leading-snug text-heading">
          {doc.title.replace(/ [—-] .*$/, "")}
        </h2>
        <div className="mt-1 text-xs text-muted">
          {[doc.author, doc.published_at ? formatDate(doc.published_at) : ""]
            .filter(Boolean).join(" · ")}
        </div>
      </div>

      {doc.summary_it && (
        <section className="rounded-xl border border-border bg-surface p-4 shadow-card">
          <h3 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
            {t("reel.summary")}
          </h3>
          <p className="text-sm leading-relaxed text-navy">{doc.summary_it}</p>
          {doc.topics?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {doc.topics.map((tp) => (
                <Badge key={tp} className="bg-white text-muted">{tp}</Badge>
              ))}
            </div>
          )}
        </section>
      )}

      {doc.arguments && doc.arguments.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-muted">
            {t("reel.arguments")}
          </h3>
          <ul className="space-y-2">
            {doc.arguments.map((a) => (
              <li key={a.id} className="rounded-xl border border-border bg-white p-3 shadow-card">
                <p className="text-sm font-semibold text-navy">{a.text_it}</p>
                {a.quote && (
                  <p className="mt-1 border-l-2 border-secondary/40 pl-2 text-xs italic text-muted">
                    “{a.quote}”
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-muted">
          {t("articles.body")}
        </h3>
        <div className="rounded-xl border border-border bg-white p-4 shadow-card">
          <AnswerBody content={doc.content_md} />
        </div>
      </section>

      <a
        href={doc.source_url}
        target="_blank"
        rel="noreferrer"
        className="mb-2 text-center text-sm font-semibold text-secondary underline underline-offset-2 hover:text-heading"
      >
        ↗ {t("articles.openOriginal")}
      </a>
    </div>
  );
}

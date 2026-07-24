import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import {
  addCustomTopic,
  deleteCustomTopic,
  fetchCustomTopics,
  fetchTopicMatches,
  type CustomTopic,
} from "../../api/customTopics";
import type { Scope } from "../../api/endpoints";
import { Badge, Button, Skeleton, fieldCls } from "../ui/primitives";
import { ReelCard } from "../reels/ReelCard";
import { ReelDetailDrawer } from "../reels/ReelDetailDrawer";
import { EASE } from "../ui/motion";

/**
 * Client-supplied themes ("Tiroide", "Osteoporosi", "Bijuva"…). The client
 * adds a theme, the engine maps every reel/blog article onto it by semantic
 * similarity — instantly, plus a nightly refresh for new content.
 */
export function CustomTopics({ scope }: { scope: Scope }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [label, setLabel] = useState("");
  const [openTopic, setOpenTopic] = useState<number | null>(null);
  const [openReel, setOpenReel] = useState<number | null>(null);

  const topics = useQuery({ queryKey: ["custom-topics"], queryFn: fetchCustomTopics });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["custom-topics"] });
    qc.invalidateQueries({ queryKey: ["coverage-map"] });
  };
  const add = useMutation({
    mutationFn: (l: string) => addCustomTopic(l),
    onSuccess: () => { setLabel(""); invalidate(); },
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteCustomTopic(id),
    onSuccess: () => { setOpenTopic(null); invalidate(); },
  });

  return (
    <section className="mb-8">
      <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
        {t("topics.title")}
      </h2>
      <p className="mb-3 text-xs text-muted/80">{t("topics.hint")}</p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          const l = label.trim();
          if (l.length >= 3) add.mutate(l);
        }}
        className="mb-4 flex max-w-xl flex-col gap-2 sm:flex-row"
      >
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={t("topics.placeholder")}
          className={fieldCls + " min-w-0 flex-1"}
        />
        <Button
          type="submit"
          variant="secondary"
          disabled={label.trim().length < 3}
          loading={add.isPending}
          className="shrink-0"
        >
          + {t("topics.add")}
        </Button>
      </form>
      {add.isPending && <p className="mb-3 text-xs text-muted">{t("topics.mapping")}</p>}
      {add.isError && (
        <p className="mb-3 text-xs font-semibold text-danger">⚠ {t("topics.addError")}</p>
      )}

      {topics.isLoading ? (
        <Skeleton className="h-12" />
      ) : (
        <div className="flex flex-wrap gap-2">
          {topics.data?.map((tp) => (
            <TopicPill
              key={tp.id}
              topic={tp}
              scope={scope}
              open={openTopic === tp.id}
              onToggle={() => setOpenTopic(openTopic === tp.id ? null : tp.id)}
              onRemove={() => {
                if (confirm(t("topics.confirmRemove", { label: tp.label }))) remove.mutate(tp.id);
              }}
            />
          ))}
          {topics.data?.length === 0 && (
            <span className="text-sm text-muted">{t("topics.empty")}</span>
          )}
        </div>
      )}

      <AnimatePresence>
        {openTopic != null && (
          <TopicMatchesPanel
            key={openTopic}
            topicId={openTopic}
            scope={scope}
            onOpenReel={setOpenReel}
          />
        )}
      </AnimatePresence>

      <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
    </section>
  );
}

function TopicPill({
  topic,
  scope,
  open,
  onToggle,
  onRemove,
}: {
  topic: CustomTopic;
  scope: Scope;
  open: boolean;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const count = scope === "medyca" ? topic.medyca_matches + topic.doc_matches : topic.competitor_matches;
  const gap = count === 0;
  return (
    <span
      className={
        "inline-flex items-center overflow-hidden rounded-full border text-sm font-semibold transition " +
        (open
          ? "border-secondary bg-surface text-heading"
          : gap
            ? "border-warning/50 bg-warning/5 text-warning"
            : "border-border bg-white text-navy hover:border-secondary")
      }
    >
      <button onClick={onToggle} className="flex min-h-10 items-center gap-2 pl-4 pr-1">
        {topic.label}
        <Badge className={gap ? "bg-warning/10 text-warning" : "bg-surface text-heading"}>
          {count}
        </Badge>
      </button>
      <button
        onClick={onRemove}
        aria-label={`Rimuovi ${topic.label}`}
        className="flex h-10 w-8 items-center justify-center text-muted/60 transition hover:text-danger"
      >
        ✕
      </button>
    </span>
  );
}

function TopicMatchesPanel({
  topicId,
  scope,
  onOpenReel,
}: {
  topicId: number;
  scope: Scope;
  onOpenReel: (id: number) => void;
}) {
  const { t } = useTranslation();
  const matches = useQuery({
    queryKey: ["topic-matches", topicId, scope],
    queryFn: () => fetchTopicMatches(topicId, scope),
  });

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.32, ease: EASE }}
      className="overflow-hidden"
    >
      <div className="mt-4 rounded-xl border border-border bg-surface p-4 shadow-card">
        {matches.isLoading ? (
          <Skeleton className="h-32" />
        ) : (
          <>
            {(matches.data?.docs.length ?? 0) > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {matches.data!.docs.map((d) => (
                  <a key={d.id} href={d.url} target="_blank" rel="noreferrer">
                    <Badge className="bg-success/10 text-success">
                      📄 {d.title.replace(/ — Medyca$/, "").slice(0, 40)}
                    </Badge>
                  </a>
                ))}
              </div>
            )}
            {(matches.data?.reels.length ?? 0) === 0 && (matches.data?.docs.length ?? 0) === 0 ? (
              <p className="text-sm text-muted">{t("topics.noMatches")}</p>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-6">
                {matches.data!.reels.map((r) => (
                  <ReelCard key={r.id} reel={r} onClick={() => onOpenReel(r.id)} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </motion.div>
  );
}

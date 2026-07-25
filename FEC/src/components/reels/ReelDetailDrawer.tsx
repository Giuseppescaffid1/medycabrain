import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import {
  addTag,
  excludeReel,
  fetchReel,
  patchAnnotation,
  removeTag,
  restoreReel,
} from "../../api/endpoints";
import type { ReelDetail } from "../../api/types";
import { Badge, Button, Spinner } from "../ui/primitives";
import { formatCount, formatLabel, mediaUrl } from "../../lib/utils";

export function ReelDetailDrawer({
  reelId,
  onClose,
}: {
  reelId: number | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: reel, isLoading } = useQuery({
    queryKey: ["reel", reelId],
    queryFn: () => fetchReel(reelId!),
    enabled: reelId != null,
  });

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onClose]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["reel", reelId] });
    qc.invalidateQueries({ queryKey: ["reels"] });
  };

  return (
    <AnimatePresence>
      {reelId != null && (
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
              <span className="text-sm font-semibold text-muted">
                {reel ? `@${reel.account.username}` : ""}
              </span>
              <button
                onClick={onClose}
                className="rounded-full px-3 py-1.5 text-sm font-semibold text-muted transition hover:bg-surface hover:text-navy"
              >
                ✕ {t("common.close")}
              </button>
            </div>

            {isLoading || !reel ? (
              <Spinner label={t("common.loading")} />
            ) : (
              <DrawerBody reel={reel} onChange={invalidate} />
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function DrawerBody({ reel, onChange }: { reel: ReelDetail; onChange: () => void }) {
  const { t } = useTranslation();
  const thumb = mediaUrl(reel.thumbnail_file) || reel.thumbnail_url || null;

  return (
    <div className="flex flex-col gap-5 p-5">
      <div className="flex gap-4">
        <div className="aspect-[9/16] w-28 shrink-0 overflow-hidden rounded-xl bg-surface">
          {thumb && <img src={thumb} alt="" className="h-full w-full object-cover" />}
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-3 text-xs font-semibold text-muted">
            <span>▶ {formatCount(reel.view_count)} {t("reel.views")}</span>
            <span>♥ {formatCount(reel.like_count)} {t("reel.likes")}</span>
            <span>💬 {formatCount(reel.comment_count)} {t("reel.comments")}</span>
          </div>
          {reel.enrichment?.content_format && (
            <Badge className="self-start">
              {formatLabel(reel.enrichment.content_format)}
            </Badge>
          )}
          <a
            href={reel.instagram_url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block text-sm font-semibold text-secondary hover:underline"
          >
            ↗ {t("reel.openInstagram")}
          </a>
        </div>
      </div>

      {reel.caption && (
        <p className="whitespace-pre-wrap text-sm text-navy">{reel.caption}</p>
      )}

      <QualityBar reel={reel} onChange={onChange} />

      {reel.enrichment ? (
        <EnrichmentCard reel={reel} />
      ) : (
        <div className="rounded-xl border border-border bg-surface p-3 text-xs text-muted">
          {t("reel.notEnriched")}
        </div>
      )}

      <TranscriptView reel={reel} />
      <AnnotationPanel reel={reel} onChange={onChange} />
    </div>
  );
}

/** Evidence the analysis rests on, off-topic flag, and the exclude control.
 *  A caption-only analysis must not read as if it described the video. */
function QualityBar({ reel, onChange }: { reel: ReelDetail; onChange: () => void }) {
  const { t } = useTranslation();
  const ev = reel.enrichment?.evidence || "transcript";
  const onTopic = reel.enrichment?.is_on_topic !== false;
  const active = reel.is_active !== false;

  const toggle = useMutation({
    mutationFn: () => (active ? excludeReel(reel.id) : restoreReel(reel.id)),
    onSuccess: onChange,
  });

  return (
    <div className="flex flex-wrap items-center gap-2">
      {ev === "transcript" && (
        <Badge className="bg-success/10 text-success">✓ {t("quality.transcript")}</Badge>
      )}
      {ev === "caption_only" && (
        <Badge className="bg-warning/10 text-warning">{t("quality.captionOnly")}</Badge>
      )}
      {ev === "insufficient" && (
        <Badge className="bg-warning/10 text-warning">{t("quality.insufficient")}</Badge>
      )}
      {!onTopic && (
        <Badge className="bg-danger/10 text-danger">
          {t("quality.offTopic")}
          {reel.enrichment?.off_topic_reason ? ` · ${reel.enrichment.off_topic_reason}` : ""}
        </Badge>
      )}
      {!active && <Badge className="bg-danger/10 text-danger">{t("quality.excluded")}</Badge>}
      <Button
        variant="ghost"
        className="ml-auto"
        loading={toggle.isPending}
        onClick={() => toggle.mutate()}
      >
        {active ? `🚫 ${t("quality.exclude")}` : `↩ ${t("quality.restore")}`}
      </Button>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-muted">
        {title}
      </h3>
      {children}
    </div>
  );
}

function EnrichmentCard({ reel }: { reel: ReelDetail }) {
  const { t } = useTranslation();
  const e = reel.enrichment!;
  return (
    <div className="flex flex-col gap-3">
      {e.summary_it && (
        <Section title={t("reel.summary")}>
          <p className="text-sm text-navy">{e.summary_it}</p>
        </Section>
      )}
      {e.topics?.length > 0 && (
        <Section title={t("reel.topics")}>
          <div className="flex flex-wrap gap-1.5">
            {e.topics.map((tp) => (
              <Badge key={tp}>{tp}</Badge>
            ))}
          </div>
        </Section>
      )}
      {e.hook_text && (
        <Section title={t("reel.hook")}>
          <p className="text-sm italic text-navy">“{e.hook_text}”</p>
          {e.hook_analysis_it && (
            <p className="mt-1 text-xs text-muted">{e.hook_analysis_it}</p>
          )}
        </Section>
      )}
      {e.target_audience_it && (
        <Section title={t("reel.audience")}>
          <p className="text-sm text-navy">{e.target_audience_it}</p>
        </Section>
      )}
      {reel.arguments?.length > 0 && (
        <Section title={t("reel.arguments")}>
          <ul className="space-y-2 text-sm text-navy">
            {reel.arguments.map((a, i) => (
              <li key={i} className="border-l-2 border-border pl-3">
                <div>{a.text}</div>
                {a.quote && (
                  <div className="mt-0.5 text-xs italic text-muted">
                    {t("reel.quote")}: “{a.quote}”
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function TranscriptView({ reel }: { reel: ReelDetail }) {
  const { t } = useTranslation();
  if (!reel.transcript || !reel.transcript.text) {
    return (
      <Section title={t("reel.transcript")}>
        <p className="text-xs text-muted">{t("reel.noTranscript")}</p>
      </Section>
    );
  }
  return (
    <Section title={t("reel.transcript")}>
      <div className="max-h-64 space-y-1 overflow-y-auto text-sm text-navy">
        {reel.transcript.segments?.length > 0 ? (
          reel.transcript.segments.map((s, i) => (
            <div key={i} className="flex gap-2">
              <span className="shrink-0 font-mono text-[10px] text-muted/70">
                {formatTime(s.start)}
              </span>
              <span>{s.text}</span>
            </div>
          ))
        ) : (
          <p>{reel.transcript.text}</p>
        )}
      </div>
    </Section>
  );
}

function AnnotationPanel({ reel, onChange }: { reel: ReelDetail; onChange: () => void }) {
  const { t } = useTranslation();
  const ann = reel.annotation;
  const [note, setNote] = useState(ann?.note ?? "");
  const [newTag, setNewTag] = useState("");

  const mutate = useMutation({
    mutationFn: (payload: Record<string, unknown>) => patchAnnotation(reel.id, payload),
    onSuccess: onChange,
  });
  const tagAdd = useMutation({
    mutationFn: (name: string) => addTag(reel.id, { name }),
    onSuccess: onChange,
  });
  const tagRemove = useMutation({
    mutationFn: (tagId: number) => removeTag(reel.id, tagId),
    onSuccess: onChange,
  });

  return (
    <Section title={t("reel.annotation")}>
      <div className="flex flex-col gap-3">
        <div className="flex gap-2">
          <ToggleChip
            active={!!ann?.is_favorite}
            onClick={() => mutate.mutate({ is_favorite: !ann?.is_favorite })}
          >
            ⭐ {t("reel.favorite")}
          </ToggleChip>
          <ToggleChip
            active={!!ann?.is_inspiration}
            onClick={() => mutate.mutate({ is_inspiration: !ann?.is_inspiration })}
          >
            💡 {t("reel.inspiration")}
          </ToggleChip>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-muted">{t("reel.note")}</label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => note !== (ann?.note ?? "") && mutate.mutate({ note })}
            placeholder={t("reel.notePlaceholder")}
            rows={2}
            className="w-full resize-none rounded-xl border border-border bg-white px-3 py-2 text-sm text-navy outline-none transition focus:border-secondary"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-muted">{t("reel.tags")}</label>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {ann?.tags?.map((tg) => (
              <button
                key={tg.id}
                onClick={() => tagRemove.mutate(tg.id)}
                className="group"
                title="Rimuovi"
              >
                <Badge color={tg.color}>
                  {tg.name} <span className="ml-1 opacity-50 group-hover:opacity-100">✕</span>
                </Badge>
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newTag.trim()) {
                  tagAdd.mutate(newTag.trim());
                  setNewTag("");
                }
              }}
              placeholder={t("reel.addTag")}
              className="flex-1 rounded-full border border-border bg-white px-4 py-1.5 text-sm text-navy outline-none transition focus:border-secondary"
            />
            <Button
              variant="ghost"
              onClick={() => {
                if (newTag.trim()) {
                  tagAdd.mutate(newTag.trim());
                  setNewTag("");
                }
              }}
            >
              +
            </Button>
          </div>
        </div>
      </div>
    </Section>
  );
}

function ToggleChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded-full border px-3 py-1.5 text-sm font-semibold transition " +
        (active
          ? "border-secondary bg-surface text-heading"
          : "border-border bg-white text-muted hover:text-navy")
      }
    >
      {children}
    </button>
  );
}

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

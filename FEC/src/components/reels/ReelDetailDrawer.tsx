import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import {
  addTag,
  fetchReel,
  patchAnnotation,
  removeTag,
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
            className="fixed inset-0 z-40 bg-black/60"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            className="fixed right-0 top-0 z-50 flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-zinc-800 bg-zinc-950 shadow-2xl"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "tween", duration: 0.25 }}
          >
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-zinc-800 bg-zinc-950/90 px-5 py-3 backdrop-blur">
              <span className="text-sm font-medium text-zinc-400">
                {reel ? `@${reel.account.username}` : ""}
              </span>
              <button
                onClick={onClose}
                className="rounded-lg px-3 py-1 text-sm text-zinc-400 hover:bg-zinc-800"
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
        <div className="aspect-[9/16] w-28 shrink-0 overflow-hidden rounded-lg bg-zinc-800">
          {thumb && <img src={thumb} alt="" className="h-full w-full object-cover" />}
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-3 text-xs text-zinc-400">
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
            className="mt-1 inline-block text-sm text-indigo-400 hover:underline"
          >
            ↗ {t("reel.openInstagram")}
          </a>
        </div>
      </div>

      {reel.caption && (
        <p className="whitespace-pre-wrap text-sm text-zinc-300">{reel.caption}</p>
      )}

      {reel.enrichment ? (
        <EnrichmentCard reel={reel} />
      ) : (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-xs text-zinc-500">
          {t("reel.notEnriched")}
        </div>
      )}

      <TranscriptView reel={reel} />
      <AnnotationPanel reel={reel} onChange={onChange} />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
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
          <p className="text-sm text-zinc-300">{e.summary_it}</p>
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
          <p className="text-sm italic text-zinc-300">“{e.hook_text}”</p>
          {e.hook_analysis_it && (
            <p className="mt-1 text-xs text-zinc-500">{e.hook_analysis_it}</p>
          )}
        </Section>
      )}
      {e.target_audience_it && (
        <Section title={t("reel.audience")}>
          <p className="text-sm text-zinc-300">{e.target_audience_it}</p>
        </Section>
      )}
      {reel.arguments?.length > 0 && (
        <Section title={t("reel.arguments")}>
          <ul className="list-disc space-y-1 pl-4 text-sm text-zinc-300">
            {reel.arguments.map((a, i) => (
              <li key={i}>{a}</li>
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
        <p className="text-xs text-zinc-500">{t("reel.noTranscript")}</p>
      </Section>
    );
  }
  return (
    <Section title={t("reel.transcript")}>
      <div className="max-h-64 space-y-1 overflow-y-auto text-sm text-zinc-300">
        {reel.transcript.segments?.length > 0 ? (
          reel.transcript.segments.map((s, i) => (
            <div key={i} className="flex gap-2">
              <span className="shrink-0 font-mono text-[10px] text-zinc-600">
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
          <label className="mb-1 block text-xs text-zinc-500">{t("reel.note")}</label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => note !== (ann?.note ?? "") && mutate.mutate({ note })}
            placeholder={t("reel.notePlaceholder")}
            rows={2}
            className="w-full resize-none rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs text-zinc-500">{t("reel.tags")}</label>
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
              className="flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500"
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
        "rounded-lg px-3 py-1.5 text-sm font-medium transition " +
        (active
          ? "bg-indigo-600/30 text-indigo-200 ring-1 ring-indigo-500"
          : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700")
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

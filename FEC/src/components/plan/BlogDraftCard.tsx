import { useState } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import type { BlogDraft } from "../../api/secondBrain";
import { Badge } from "../ui/primitives";
import { AnswerBody } from "../knowledge/AnswerBody";
import { useCopy } from "../../lib/clipboard";
import { ActionButton, IconCopy, IconStarSmall, IconX } from "./IdeaCard";

/**
 * A blog draft the platform wrote from a theme: either an expansion of the
 * article Medyca already has ("espansione") or a new one ("bozza").
 *
 * Collapsed it shows the first lines; opened it renders the whole text. The
 * body has no citation buttons: the drafts carry their sources in the model
 * output, and a `[n]` that jumps nowhere would only look broken.
 */
export function BlogDraftCard({
  draft,
  onSave,
  onDismiss,
}: {
  draft: BlogDraft;
  onSave: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { copy, state: copyState } = useCopy();
  const saved = draft.status === "saved";

  return (
    <motion.article
      layout
      className="overflow-hidden rounded-2xl border border-border bg-surface shadow-card"
    >
      <div className="px-4 pb-3 pt-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge className="bg-white text-secondary">
            {draft.mode === "expand" ? t("blog.modeExpand") : t("blog.modeDraft")}
          </Badge>
          {draft.cluster_label && (
            <Badge className="bg-white text-muted">
              {t("blog.theme")}: {draft.cluster_label}
            </Badge>
          )}
          {saved && <Badge className="bg-success/10 text-success">{t("plan.kept")}</Badge>}
        </div>
        <h3 className="text-sm font-bold leading-snug text-heading">
          {draft.title || draft.cluster_label}
        </h3>
        {open ? (
          <div className="mt-3 rounded-xl border border-border bg-white p-4">
            <AnswerBody content={draft.content_md} />
          </div>
        ) : (
          <p className="mt-2 line-clamp-3 whitespace-pre-line text-xs leading-relaxed text-muted">
            {draft.content_md}
          </p>
        )}
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="mt-2 text-xs font-semibold text-secondary hover:text-heading"
        >
          {open ? t("blog.collapse") : t("blog.readAll")}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-border bg-white/60 px-4 py-2.5">
        <ActionButton
          onClick={() => copy(`# ${draft.title}\n\n${draft.content_md}`)}
          state={copyState === "done" ? "done" : copyState === "error" ? "error" : "idle"}
          label={t("blog.copy")}
          doneLabel={t("plan.copied")}
          errorLabel={t("plan.copyFailed")}
          icon={<IconCopy />}
        />
        <ActionButton
          onClick={onSave}
          state={saved ? "done" : "idle"}
          label={t("plan.save")}
          doneLabel={t("plan.kept")}
          icon={<IconStarSmall filled={saved} />}
          tone="success"
        />
        <ActionButton
          onClick={onDismiss}
          state="idle"
          label={t("plan.dismiss")}
          icon={<IconX />}
          tone="muted"
          className="ml-auto"
        />
      </div>
    </motion.article>
  );
}

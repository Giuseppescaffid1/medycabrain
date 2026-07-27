import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import type { ContentIdea } from "../../api/secondBrain";
import { Badge } from "../ui/primitives";
import { EASE } from "../ui/motion";
import { useCopy } from "../../lib/clipboard";
import { cn } from "../../lib/utils";

/**
 * One content, from the idea to the shot list.
 *
 * Collapsed it answers "is this worth filming"; expanded it answers "what do
 * I actually say", step by step. Actions confirm what they did — a control
 * that changes nothing visible reads as broken even when it worked, which is
 * exactly what happened while the copy button was silently failing.
 */
export function IdeaCard({
  idea,
  onSave,
  onDismiss,
}: {
  idea: ContentIdea;
  onSave: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { copy, state: copyState } = useCopy();

  const asText = () =>
    [
      idea.argument_it,
      "",
      `${t("plan.hook")}: ${idea.hook_it}`,
      "",
      ...(idea.outline ?? []).map(
        (s, i) => `${i + 1}. ${s.step}${s.note ? `  (${s.note})` : ""}`
      ),
      "",
      idea.cta_it ? `${t("plan.cta")}: ${idea.cta_it}` : "",
      `${t("plan.angle")}: ${idea.angle_it}`,
      `${t("plan.why")}: ${idea.rationale_it}`,
    ]
      .filter(Boolean)
      .join("\n");

  const saved = idea.status === "saved";

  return (
    <motion.article
      layout
      className="overflow-hidden rounded-2xl border border-border bg-surface shadow-card transition duration-200 hover:shadow-float"
    >
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full px-4 pb-3 pt-4 text-left"
      >
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {idea.is_gap && <Badge className="bg-warning/10 text-warning">{t("plan.gap")}</Badge>}
          {idea.content_format && (
            <Badge className="bg-white text-secondary">
              {idea.content_format.replace("_", " ")}
            </Badge>
          )}
          {idea.outline?.length > 0 && (
            <Badge className="bg-white text-muted">
              {idea.outline.length} {t("plan.steps")}
            </Badge>
          )}
          {saved && <Badge className="bg-success/10 text-success">{t("plan.kept")}</Badge>}
          <span className="ml-auto flex items-center gap-1 text-xs font-semibold text-secondary">
            {open ? t("plan.collapse") : t("plan.expand")}
            <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none" aria-hidden>
                <path d="m5 8 5 5 5-5" stroke="currentColor" strokeWidth="2"
                      strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </motion.span>
          </span>
        </div>

        <h3 className="text-base font-bold text-heading">{idea.argument_it}</h3>

        {idea.hook_it && (
          <div className="mt-3 rounded-xl border-l-2 border-secondary bg-white p-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-muted">
              {t("plan.hook")}
            </div>
            <p className="mt-0.5 text-sm italic text-navy">“{idea.hook_it}”</p>
          </div>
        )}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="space-y-4 px-4 pb-4">
              {idea.outline?.length > 0 && (
                <div>
                  <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted">
                    {t("plan.outline")}
                  </div>
                  <ol className="relative space-y-3 border-l border-border pl-5">
                    {idea.outline.map((s, i) => (
                      <li key={i} className="relative">
                        <span className="absolute -left-[26px] flex h-5 w-5 items-center justify-center rounded-full bg-secondary/12 text-[10px] font-bold text-secondary">
                          {i + 1}
                        </span>
                        <p className="text-sm text-navy">{s.step}</p>
                        {s.note && (
                          <p className="mt-0.5 text-xs italic text-muted">{s.note}</p>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {idea.cta_it && (
                <div className="rounded-xl border border-success/30 bg-success/5 p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-success">
                    {t("plan.cta")}
                  </div>
                  <p className="mt-0.5 text-sm text-navy">{idea.cta_it}</p>
                </div>
              )}

              {idea.angle_it && (
                <p className="text-sm text-navy">
                  <span className="font-bold">{t("plan.angle")}:</span> {idea.angle_it}
                </p>
              )}
              {idea.rationale_it && (
                <p className="text-sm text-muted">
                  <span className="font-bold">{t("plan.why")}:</span> {idea.rationale_it}
                </p>
              )}

              {idea.source_refs?.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted">
                    {t("plan.sources")}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {idea.source_refs.map((s, i) => (
                      <Badge
                        key={i}
                        className={
                          s.kind === "competitor"
                            ? "bg-warning/10 text-warning"
                            : "bg-success/10 text-success"
                        }
                      >
                        {s.kind === "blog" ? "📄" : s.kind === "competitor" ? "🏷" : "🎬"}{" "}
                        {s.title.slice(0, 42)}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex flex-wrap items-center gap-2 border-t border-border bg-white/60 px-4 py-2.5">
        <ActionButton
          onClick={() => copy(asText())}
          state={copyState === "done" ? "done" : copyState === "error" ? "error" : "idle"}
          label={t("plan.copy")}
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

/** A control that says what it did. The label swaps on success and swaps
 *  back, so a click always produces something the eye can catch. */
function ActionButton({
  onClick, state, label, doneLabel, errorLabel, icon, tone = "secondary", className,
}: {
  onClick: () => void;
  state: "idle" | "done" | "error";
  label: string;
  doneLabel?: string;
  errorLabel?: string;
  icon: React.ReactNode;
  tone?: "secondary" | "success" | "muted";
  className?: string;
}) {
  const shown = state === "done" ? doneLabel ?? label : state === "error" ? errorLabel ?? label : label;
  const colour =
    state === "error"
      ? "text-danger"
      : state === "done"
        ? "text-success"
        : tone === "muted"
          ? "text-muted hover:text-danger"
          : tone === "success"
            ? "text-muted hover:text-success"
            : "text-muted hover:text-secondary";

  return (
    <motion.button
      onClick={onClick}
      whileTap={{ scale: 0.94 }}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-bold transition duration-200 hover:bg-surface",
        colour,
        className
      )}
    >
      <motion.span
        key={state}
        initial={{ scale: 0.7, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.18, ease: EASE }}
        className="flex"
      >
        {state === "done" ? <IconCheck /> : icon}
      </motion.span>
      {shown}
    </motion.button>
  );
}

const stroke = {
  fill: "none", stroke: "currentColor", strokeWidth: 1.9,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
};

const IconCopy = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...stroke} aria-hidden>
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15V5a2 2 0 0 1 2-2h10" />
  </svg>
);

const IconCheck = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...stroke} aria-hidden>
    <path d="m4 12.5 5 5L20 6.5" />
  </svg>
);

const IconX = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...stroke} aria-hidden>
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
);

const IconStarSmall = ({ filled }: { filled?: boolean }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" {...stroke}
       fill={filled ? "currentColor" : "none"} aria-hidden>
    <path d="m12 3.6 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />
  </svg>
);

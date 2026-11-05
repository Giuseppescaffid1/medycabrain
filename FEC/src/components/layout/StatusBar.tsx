import { useTranslation } from "react-i18next";
import { useJobs } from "../../contexts/JobsContext";
import type { Job } from "../../api/jobs";

/**
 * Global background-job status bar ("tmux bar"). Sits in the page flow, under
 * `<main>`, and only when there is something to report: pages get shorter
 * instead of being covered (a fixed bar hid the chat's send row). It persists
 * across navigation so a long run stays visible while the user works
 * elsewhere. On the Home, which is a full-screen page with no shell, it floats.
 */
export function StatusBar({ floating = false }: { floating?: boolean }) {
  const { jobs, dismiss, lastError, clearError } = useJobs();
  const { t } = useTranslation();
  if (jobs.length === 0 && !lastError) return null;

  return (
    <div
      className={
        floating
          ? "pointer-events-none fixed inset-x-0 bottom-0 z-40 flex flex-col items-center gap-2 p-3"
          : "flex max-h-[40vh] shrink-0 flex-col items-center gap-2 overflow-y-auto border-t border-border bg-ground p-2 sm:p-3"
      }
    >
      {lastError && (
        <div
          role="alert"
          className="pointer-events-auto flex w-full max-w-2xl items-center gap-3 rounded-xl border border-danger/50 bg-white px-4 py-3 text-sm"
        >
          <span aria-hidden>⚠️</span>
          <span className="min-w-0 flex-1 font-semibold text-navy">
            {t("jobs.startFailed")} {lastError}
          </span>
          <button
            onClick={clearError}
            className="shrink-0 rounded-full px-2 py-1 text-xs text-muted hover:text-navy"
            aria-label={t("common.close")}
          >
            ✕
          </button>
        </div>
      )}
      {jobs.map((job) => (
        <JobRow key={job.id} job={job} onDismiss={() => dismiss(job.id)} />
      ))}
    </div>
  );
}

function JobRow({ job, onDismiss }: { job: Job; onDismiss: () => void }) {
  const { t } = useTranslation();
  const active = job.status === "queued" || job.status === "running";
  const failed = job.status === "failed";
  const done = job.status === "done";

  const accent = failed
    ? "border-danger/50"
    : done
      ? "border-success/50"
      : "border-secondary/50";

  const label = t(`jobs.${job.kind}`, { defaultValue: t("jobs.pipeline") });

  return (
    <div
      className={
        "pointer-events-auto w-full max-w-2xl rounded-xl border bg-white/95 px-4 py-3 shadow-float backdrop-blur " +
        accent
      }
    >
      <div className="flex items-center gap-3">
        <span className="text-lg">
          {failed ? "⚠️" : done ? "✅" : "🧠"}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <span className="truncate text-sm font-bold text-navy">{label}</span>
            <span className="shrink-0 text-xs font-semibold text-muted">
              {active ? `${job.progress}%` : failed ? t("jobs.failed") : t("jobs.done")}
            </span>
          </div>
          <div className="mt-1 truncate text-xs text-muted">{job.message}</div>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface">
            <div
              className={
                "h-full rounded-full transition-all duration-500 " +
                (failed ? "bg-danger" : done ? "bg-success" : "bg-secondary")
              }
              style={{ width: `${active ? Math.max(job.progress, 4) : 100}%` }}
            />
          </div>
        </div>
        {!active && (
          <button
            onClick={onDismiss}
            className="shrink-0 rounded-full px-2 py-1 text-xs text-muted hover:text-navy"
            aria-label={t("common.close")}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

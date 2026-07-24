import { useTranslation } from "react-i18next";
import { useJobs } from "../../contexts/JobsContext";
import type { Job } from "../../api/jobs";

/**
 * Global background-job status bar ("tmux bar"). Fixed at the bottom of the
 * app shell, shown only when there are jobs to report. Persists across page
 * navigation so a long idea-generation run stays visible while the user
 * works elsewhere.
 */
export function StatusBar() {
  const { jobs, dismiss } = useJobs();
  if (jobs.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex flex-col items-center gap-2 p-3">
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
    ? "border-red-600/50 bg-red-950/80"
    : done
      ? "border-emerald-600/50 bg-emerald-950/80"
      : "border-indigo-600/50 bg-zinc-900/90";

  const label = t(`jobs.${job.kind}`, { defaultValue: t("jobs.pipeline") });

  return (
    <div
      className={
        "pointer-events-auto w-full max-w-2xl rounded-xl border px-4 py-3 shadow-2xl backdrop-blur " +
        accent
      }
    >
      <div className="flex items-center gap-3">
        <span className="text-lg">
          {failed ? "⚠️" : done ? "✅" : "🧠"}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <span className="truncate text-sm font-semibold text-white">{label}</span>
            <span className="shrink-0 text-xs text-zinc-400">
              {active ? `${job.progress}%` : failed ? t("jobs.failed") : t("jobs.done")}
            </span>
          </div>
          <div className="mt-1 truncate text-xs text-zinc-400">{job.message}</div>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
            <div
              className={
                "h-full rounded-full transition-all duration-500 " +
                (failed ? "bg-red-500" : done ? "bg-emerald-500" : "bg-indigo-500")
              }
              style={{ width: `${active ? Math.max(job.progress, 4) : 100}%` }}
            />
          </div>
        </div>
        {!active && (
          <button
            onClick={onDismiss}
            className="shrink-0 rounded px-2 py-1 text-xs text-zinc-500 hover:text-zinc-300"
            aria-label={t("common.close")}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

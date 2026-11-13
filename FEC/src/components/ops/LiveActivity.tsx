import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

/**
 * "In questo momento", reduced to one line and a link.
 *
 * What is running, stage by stage and item by item, now lives on the
 * Avanzamento page (`/avanzamento`); keeping the same list here would show the
 * same numbers in two places. What stays is the re-analysis bar, which that
 * page does not cover.
 */
export interface Job {
  job: string;
  label: string;
  pid: number;
  seconds: number;
  stage: string;
  detail: string;
}

export interface Reanalysis {
  model: string;
  done: number;
  total: number;
  pct: number;
}

export function LiveActivity({
  jobs,
  reanalysis,
}: {
  jobs: Job[];
  reanalysis?: Reanalysis | null;
  updatedAt?: number;
}) {
  const { t } = useTranslation();

  return (
    <section>
      <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
        {t("ops.live")}
      </h2>
      <p className="mb-3 text-xs text-muted/80">{t("ops.liveLinkHint")}</p>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-xl border border-border bg-surface p-4 shadow-card">
        <span className="flex items-center gap-2 text-sm font-semibold text-navy">
          {jobs.length > 0 && (
            <span className="h-2 w-2 shrink-0 rounded-full bg-success motion-safe:animate-pulse" aria-hidden />
          )}
          {jobs.length > 0 ? `${jobs.length} ${t("ops.running")}` : t("ops.idleShort")}
        </span>
        <Link
          to="/avanzamento"
          className="min-h-10 rounded-full px-1 py-2 text-sm font-bold text-secondary underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary"
        >
          {t("ops.liveLink")}
        </Link>
      </div>

      {reanalysis && reanalysis.done < reanalysis.total && (
        <div className="mt-3 rounded-xl border border-border bg-surface p-4 shadow-card">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm font-bold text-navy">{t("ops.reanalysis")}</span>
            <span className="text-xs font-semibold tabular-nums text-muted">
              {reanalysis.done}/{reanalysis.total} · {reanalysis.pct}%
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-white">
            <div
              className="h-full rounded-full bg-brand transition-all duration-700"
              style={{ width: `${Math.max(reanalysis.pct, 1)}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-muted">
            {t("ops.reanalysisHint", { model: reanalysis.model })}
          </p>
        </div>
      )}
    </section>
  );
}

import { useTranslation } from "react-i18next";
import { Badge } from "../ui/primitives";
import { elapsedNow, fmtDuration, useTicker } from "./live";

/**
 * What the machine is doing right now.
 *
 * The stage bars elsewhere on this page only move when a stage finishes, and
 * a stage such as the transcription runs for the best part of an hour. During
 * that hour the page looked frozen, which reads as "nothing is happening" at
 * the exact moment most is. This panel reads the running processes instead,
 * so there is always something that visibly advances.
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
  updatedAt,
}: {
  jobs: Job[];
  reanalysis?: Reanalysis | null;
  updatedAt?: number;
}) {
  const { t } = useTranslation();
  useTicker(jobs.length > 0);

  return (
    <section>
      <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
        {t("ops.live")}
      </h2>
      <p className="mb-3 text-xs text-muted/80">{t("ops.liveHint")}</p>

      {jobs.length === 0 ? (
        <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted shadow-card">
          {t("ops.idle")}
        </p>
      ) : (
        <div className="space-y-2">
          {jobs.map((j) => (
            <div
              key={j.pid}
              className="rounded-xl border border-secondary/30 bg-secondary/5 p-4 shadow-card"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <span
                  className="h-2 w-2 shrink-0 rounded-full bg-success motion-safe:animate-pulse"
                  aria-hidden
                />
                <span className="text-sm font-bold text-navy">{j.label}</span>
                {j.stage && (
                  <Badge className="bg-white text-secondary">{j.stage}</Badge>
                )}
                <span className="ml-auto shrink-0 text-xs font-semibold tabular-nums text-muted">
                  {t("ops.since")} {fmtDuration(elapsedNow(j.seconds, updatedAt))}
                </span>
              </div>
              {j.detail && (
                <p className="mt-2 break-words text-xs text-muted">{j.detail}</p>
              )}
            </div>
          ))}
        </div>
      )}

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

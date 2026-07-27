import { useTranslation } from "react-i18next";
import { Badge } from "../ui/primitives";
import { elapsedNow, fmtDuration, useTicker } from "./live";

/**
 * How long each pipeline run actually took, stage by stage.
 *
 * Bars are proportional to real duration within a run, so the stage that eats
 * the night is obvious at a glance — which is the whole point: when the client
 * asks "why isn't it finished", the answer should be visible rather than
 * looked up in a log over SSH.
 */
export interface RunStage {
  stage: string;
  label: string;
  started: string | null;
  finished: string | null;
  seconds: number;
  result: string;
  /** Started and not yet finished: its duration is still growing. */
  running?: boolean;
}

export interface Run {
  started: string;
  finished?: string;
  seconds: number;
  stages: RunStage[];
  running?: boolean;
}

const STAGE_COLOUR: Record<string, string> = {
  scrape: "bg-secondary",
  download: "bg-warning",
  transcribe: "bg-success",
  enrich: "bg-brand",
  embed: "bg-secondary/60",
  knowledge: "bg-muted",
  cluster: "bg-heading",
};

const fmtStart = (iso: string) =>
  new Date(iso).toLocaleString("it-IT", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });

export function RunTimeline({ runs, updatedAt }: { runs: Run[]; updatedAt?: number }) {
  const { t } = useTranslation();
  // A run in flight has a segment that grows; without a tick it would only
  // move when the poll lands, and the bar would look stuck between polls.
  useTicker(runs?.some((r) => r.running) ?? false);
  if (!runs?.length) return <p className="text-sm text-muted">{t("ops.noRuns")}</p>;

  return (
    <div className="space-y-3">
      {runs.map((run) => {
        const secs = (s: RunStage) =>
          s.running ? elapsedNow(s.seconds, updatedAt) : s.seconds;
        const total = Math.max(run.stages.reduce((n, s) => n + secs(s), 0), 1);
        return (
          <div
            key={run.started}
            className="rounded-xl border border-border bg-surface p-4 shadow-card"
          >
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-bold text-navy">{fmtStart(run.started)}</span>
              <span className="flex items-center gap-2">
                {run.running && (
                  <Badge className="bg-success/10 text-success">
                    <span
                      className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-success motion-safe:animate-pulse"
                      aria-hidden
                    />
                    {t("ops.running")}
                  </Badge>
                )}
                <Badge className="bg-white text-heading">
                  {t("ops.total")} {fmtDuration(total)}
                </Badge>
              </span>
            </div>

            {/* proportional bar: one segment per stage */}
            <div className="mb-3 flex h-2.5 w-full overflow-hidden rounded-full bg-white">
              {run.stages.map((s) => (
                <div
                  key={s.stage}
                  className={
                    (STAGE_COLOUR[s.stage] ?? "bg-muted") +
                    (s.running ? " motion-safe:animate-pulse" : "")
                  }
                  style={{ width: `${Math.max((secs(s) / total) * 100, 0.8)}%` }}
                  title={`${s.label}: ${fmtDuration(secs(s))}`}
                />
              ))}
            </div>

            <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {run.stages.map((s) => (
                <li key={s.stage} className="flex items-center gap-2 text-xs">
                  <span
                    className={
                      "h-2 w-2 shrink-0 rounded-full " + (STAGE_COLOUR[s.stage] ?? "bg-muted")
                    }
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 truncate text-navy">
                    {s.label}
                    {s.running && (
                      <span className="ml-1.5 font-semibold text-success">
                        · {t("ops.running")}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 tabular-nums font-semibold text-muted">
                    {fmtDuration(secs(s))}
                  </span>
                  <span className="w-12 shrink-0 text-right tabular-nums text-muted/70">
                    {Math.round((secs(s) / total) * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

import { useTranslation } from "react-i18next";
import { Badge } from "../ui/primitives";

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
  finished: string;
  seconds: number;
  result: string;
}

export interface Run {
  started: string;
  finished?: string;
  seconds: number;
  stages: RunStage[];
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

export const fmtDuration = (s: number) =>
  s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;

const fmtStart = (iso: string) =>
  new Date(iso).toLocaleString("it-IT", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });

export function RunTimeline({ runs }: { runs: Run[] }) {
  const { t } = useTranslation();
  if (!runs?.length) return <p className="text-sm text-muted">{t("ops.noRuns")}</p>;

  return (
    <div className="space-y-3">
      {runs.map((run) => {
        const total = Math.max(run.seconds, 1);
        return (
          <div
            key={run.started}
            className="rounded-xl border border-border bg-surface p-4 shadow-card"
          >
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-bold text-navy">{fmtStart(run.started)}</span>
              <Badge className="bg-white text-heading">
                {t("ops.total")} {fmtDuration(run.seconds)}
              </Badge>
            </div>

            {/* proportional bar: one segment per stage */}
            <div className="mb-3 flex h-2.5 w-full overflow-hidden rounded-full bg-white">
              {run.stages.map((s) => (
                <div
                  key={s.stage}
                  className={STAGE_COLOUR[s.stage] ?? "bg-muted"}
                  style={{ width: `${Math.max((s.seconds / total) * 100, 0.8)}%` }}
                  title={`${s.label}: ${fmtDuration(s.seconds)}`}
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
                  <span className="min-w-0 flex-1 truncate text-navy">{s.label}</span>
                  <span className="shrink-0 tabular-nums font-semibold text-muted">
                    {fmtDuration(s.seconds)}
                  </span>
                  <span className="w-12 shrink-0 text-right tabular-nums text-muted/70">
                    {Math.round((s.seconds / total) * 100)}%
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

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { apiClient } from "../../api/client";
import { Button } from "../ui/primitives";
import { fmtDuration } from "./live";

/**
 * How much is left to process, how long it should take, and the button that
 * starts it now.
 *
 * The stage bars below this panel answer "how far has it got". They cannot
 * answer the question actually asked — *quanto manca?* — because a percentage
 * says nothing about whether the remainder is ten minutes or ten hours. The
 * counts and the estimate both come from the server (`core/queue_eta.py`),
 * measured from the recent runs rather than assumed, so this panel never
 * promises a number the machine has not actually achieved.
 *
 * Until now the pipeline only ran from cron, so adding an account meant
 * waiting for the night to see anything. "Aggiorna ora" queues the same run.
 */
export interface QueueStage {
  key: string;
  label: string;
  pending: number;
  waiting: number;
  failed: number;
  seconds_per_item: number;
  eta_seconds: number;
  measured: boolean;
  runs: number;
}

export interface QueueData {
  remaining: number;
  total: number;
  eta_seconds: number;
  measured: boolean;
  failed: number;
  stages: QueueStage[];
}

/** What collection has cost this billing cycle. */
export interface Budget {
  plan: string;
  spent_usd: number;
  limit_usd: number;
  ceiling_usd: number;
  available_usd: number;
  cycle_start: string | null;
  cycle_end: string | null;
}

export interface RunningJob {
  id: number;
  kind: string;
  status: string;
  progress: number;
  message: string;
}

export function PipelineQueue({
  queue,
  job,
  budget,
  onStarted,
}: {
  queue?: QueueData;
  job?: RunningJob;
  budget?: Budget | null;
  onStarted: () => void;
}) {
  const { t } = useTranslation();
  const [error, setError] = useState("");

  const run = useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post("/ops/run/", {});
      return data;
    },
    onSuccess: () => {
      setError("");
      onStarted();
    },
    onError: (e: unknown) => {
      // The server explains the refusal in the client's own language (an
      // update already running, most often). Show that, not a status code.
      const detail = (e as { response?: { data?: { detail?: string } } })?.response
        ?.data?.detail;
      setError(detail || t("common.error"));
    },
  });

  if (!queue) return null;

  const busy = Boolean(job) || run.isPending;
  const idle = queue.remaining === 0;

  return (
    <section>
      <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
        {t("queue.title")}
      </h2>
      <p className="mb-3 text-xs text-muted/80">{t("queue.hint")}</p>

      <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
        {/* The two numbers, then the action. Stacked at 380px, side by side
            as soon as there is room. */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
            <div>
              <div className="text-xs font-bold uppercase tracking-wider text-muted">
                {t("queue.remaining")}
              </div>
              <div className="mt-0.5 flex items-baseline gap-2">
                <span className="text-3xl font-bold tabular-nums text-navy">
                  {queue.remaining}
                </span>
                <span className="text-sm text-muted">
                  {t("queue.ofTotal", { total: queue.total })}
                </span>
              </div>
            </div>

            <div>
              <div className="text-xs font-bold uppercase tracking-wider text-muted">
                {t("queue.wait")}
              </div>
              <div className="mt-0.5 text-3xl font-bold tabular-nums text-navy">
                {idle ? "—" : fmtDuration(queue.eta_seconds)}
              </div>
            </div>
          </div>

          <Button
            onClick={() => run.mutate()}
            disabled={busy}
            loading={run.isPending}
            className="shrink-0"
          >
            {job ? t("queue.running") : t("queue.run")}
          </Button>
        </div>

        {/* What the machine is doing right now takes the place of the
            estimate: while a run is live, its own progress is the truth. */}
        {job && (
          <div className="mt-4">
            <div className="mb-1 flex flex-wrap justify-between gap-2 text-xs text-muted">
              <span>{job.message || t("queue.running")}</span>
              <span className="tabular-nums">{job.progress}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-white">
              <div
                className="h-full rounded-full bg-secondary transition-all duration-700"
                style={{ width: `${Math.max(job.progress, 2)}%` }}
              />
            </div>
          </div>
        )}

        {error && (
          <p className="mt-3 flex items-start gap-2 text-sm font-semibold text-danger">
            <span aria-hidden>⚠</span>
            <span>{error}</span>
          </p>
        )}

        {idle && !job ? (
          <p className="mt-4 text-sm text-muted">{t("queue.empty")}</p>
        ) : (
          <ul className="mt-4 space-y-2 border-t border-border pt-3">
            {queue.stages.map((s) => (
              <li
                key={s.key}
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm"
              >
                <span className={s.waiting > 0 ? "text-navy" : "text-muted"}>
                  {s.label}
                </span>
                <span className="flex items-baseline gap-2 text-xs text-muted">
                  <span className="font-semibold tabular-nums text-navy">
                    {s.waiting}
                  </span>
                  {s.waiting > 0 && (
                    <span className="tabular-nums">
                      · {fmtDuration(s.eta_seconds)}
                    </span>
                  )}
                  {s.failed > 0 && (
                    <span className="tabular-nums text-danger">
                      · {t("queue.failedCount", { count: s.failed })}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}

        {/* Never let the estimate pass for a measurement it is not. */}
        {!idle && (
          <p className="mt-3 text-xs text-muted/80">
            {queue.measured ? t("queue.measured") : t("queue.estimated")}
          </p>
        )}
      </div>

      {/* What collection costs. On a $5 cycle this belongs next to the button
          that spends it, not buried in a settings page. */}
      {budget && <BudgetBar budget={budget} />}
    </section>
  );
}

function BudgetBar({ budget }: { budget: Budget }) {
  const { t } = useTranslation();
  const pct = budget.ceiling_usd
    ? Math.min(100, Math.round((budget.spent_usd / budget.ceiling_usd) * 100))
    : 0;
  // Amber past two thirds, red at the ceiling — the ceiling is where
  // collection stops, so it must not arrive as a surprise.
  const tone = pct >= 100 ? "bg-danger" : pct >= 67 ? "bg-warning" : "bg-success";
  const renews = budget.cycle_end
    ? new Date(budget.cycle_end).toLocaleDateString("it-IT", {
        day: "numeric",
        month: "long",
      })
    : "";

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface p-4 shadow-card">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-sm font-bold text-navy">{t("queue.budget")}</span>
        <span className="text-xs font-semibold tabular-nums text-muted">
          ${budget.spent_usd.toFixed(2)} / ${budget.ceiling_usd.toFixed(2)}
        </span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-white"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t("queue.budget")}
      >
        <div
          className={"h-full rounded-full transition-all duration-700 " + tone}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-muted">
        {pct >= 100
          ? t("queue.budgetStopped")
          : t("queue.budgetLeft", {
              left: budget.available_usd.toFixed(2),
              renews,
            })}
      </p>
    </div>
  );
}

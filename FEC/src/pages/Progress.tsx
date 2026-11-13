import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { fetchProgress, type RoundData } from "../api/progress";
import { PanelError } from "../components/manage/parts";
import { Skeleton } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";
import { fmtDuration, useTicker } from "../components/ops/live";
import { BatchBlock } from "../components/progress/BatchBlock";
import { DailyTotals } from "../components/progress/DailyTotals";
import { ModelLines } from "../components/progress/ModelLines";
import { StageCard } from "../components/progress/StageCard";
import { clock, whenLabel } from "../components/progress/format";

/**
 * "Avanzamento": what is running right now, stage by stage, in the manner of
 * tqdm — and who is doing each item (local model, remote model, bulk delivery,
 * no model). Read-only: nothing here starts, stops or retries anything.
 *
 * It polls a light endpoint every 2 s while something runs and every 15 s when
 * everything is still (react-query pauses it on a hidden tab). The elapsed
 * times tick locally every second, so a 2 s poll never looks like a stall.
 */
export default function Progress() {
  const { t } = useTranslation();
  const { data, isLoading, isError, dataUpdatedAt, refetch, isFetching } = useQuery({
    queryKey: ["ops-progress"],
    queryFn: fetchProgress,
    refetchInterval: (q) => (q.state.data?.running ? 2000 : 15000),
  });
  useTicker(!!data?.running);

  const rounds = data?.rounds ?? [];
  const active = rounds.filter((r) => r.active);
  const last = active.length === 0 ? rounds[0] : undefined;
  const nothingEver = !!data && rounds.length === 0 && data.jobs.length === 0
    && data.other_calls.length === 0;

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-4 sm:px-6">
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-heading">{t("progress.title")}</h1>
            <p className="text-sm text-muted">
              {t("progress.subtitle")}
              {dataUpdatedAt
                ? ` · ${t("progress.updatedAt")} ${new Date(dataUpdatedAt).toLocaleTimeString("it-IT")}`
                : ""}
            </p>
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex min-h-10 shrink-0 items-center gap-2 rounded-full border border-border bg-white px-4 py-2 text-sm font-bold text-secondary shadow-card transition duration-200 hover:bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary disabled:opacity-60"
          >
            <svg
              width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden
              className={isFetching ? "motion-safe:animate-spin" : ""}
            >
              <path
                d="M14 8a6 6 0 1 1-1.76-4.24M14 2v4h-4"
                stroke="currentColor" strokeWidth="1.8"
                strokeLinecap="round" strokeLinejoin="round"
              />
            </svg>
            {t("progress.refresh")}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
          <div className="mx-auto max-w-3xl space-y-6">
            {isLoading ? (
              <Skeleton className="h-64" />
            ) : !data ? (
              <PanelError message={t("progress.loadError")} onRetry={() => refetch()} />
            ) : (
              <>
                {isError && (
                  <p role="alert" className="rounded-xl bg-warning/10 px-4 py-2 text-xs font-semibold text-warning">
                    {t("progress.staleError", {
                      time: new Date(dataUpdatedAt).toLocaleTimeString("it-IT", {
                        hour: "2-digit", minute: "2-digit",
                      }),
                    })}
                  </p>
                )}

                <section>
                  <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                    {t("progress.now")}
                  </h2>
                  <p className="mb-3 text-xs text-muted/80">{t("progress.nowHint")}</p>

                  {nothingEver ? (
                    <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted shadow-card">
                      {t("progress.empty")}
                    </p>
                  ) : (
                    <div className="space-y-5">
                      {active.map((r) => (
                        <Round key={r.run_id} round={r} updatedAt={dataUpdatedAt} />
                      ))}

                      {last && (
                        <>
                          <div className="rounded-xl border border-border bg-surface p-4 text-sm text-navy shadow-card">
                            <p className="font-semibold">{t("progress.idle")}</p>
                            <p className="mt-1 text-xs text-muted">{lastRoundLine(last, t)}</p>
                            <p className="mt-1 text-xs text-muted">
                              {t("progress.nextRounds")}{" "}
                              <Link to="/stato" className="font-semibold text-secondary underline underline-offset-2">
                                {t("progress.nextRoundsLink")}
                              </Link>
                            </p>
                          </div>
                          <Round round={last} updatedAt={dataUpdatedAt} />
                        </>
                      )}

                      {data.jobs.length > 0 && (
                        <div>
                          <h3 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                            {t("progress.jobs")}
                          </h3>
                          <p className="mb-2 text-xs text-muted/80">{t("progress.jobsHint")}</p>
                          <ul className="space-y-2">
                            {data.jobs.map((j) => (
                              <li key={j.id} className="rounded-xl border border-secondary/30 bg-secondary/5 p-4 shadow-card">
                                <div className="flex items-baseline justify-between gap-3 text-sm">
                                  <span className="min-w-0 font-bold text-navy">{j.kind_label}</span>
                                  <span className="shrink-0 font-bold tabular-nums text-navy">{j.progress}%</span>
                                </div>
                                <div
                                  role="progressbar"
                                  aria-label={j.kind_label}
                                  aria-valuemin={0}
                                  aria-valuemax={100}
                                  aria-valuenow={j.progress}
                                  className="mt-2 h-2 w-full overflow-hidden rounded-full bg-white"
                                >
                                  <div
                                    className="h-full rounded-full bg-secondary motion-safe:transition-all motion-safe:duration-700"
                                    style={{ width: `${Math.max(j.progress, 1)}%` }}
                                  />
                                </div>
                                {j.message && <p className="mt-2 break-words text-xs text-muted">{j.message}</p>}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {data.other_calls.length > 0 && (
                        <div>
                          <h3 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                            {t("progress.otherCalls")}
                          </h3>
                          <p className="text-xs text-muted/80">{t("progress.otherCallsHint")}</p>
                          <ModelLines items={data.other_calls} more={0} updatedAt={dataUpdatedAt} />
                        </div>
                      )}
                    </div>
                  )}
                </section>

                <BatchBlock batches={data.batches} />
              </>
            )}

            <DailyTotals />
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

function lastRoundLine(r: RoundData, t: (k: string, o?: Record<string, unknown>) => string) {
  if (r.interrupted) {
    return t("progress.interrupted", { time: clock(r.finished_at ?? r.started_at) });
  }
  const finished = r.stages.filter((s) => s.status === "done").length;
  const start = r.started_at ? new Date(r.started_at).getTime() : 0;
  const end = r.finished_at ? new Date(r.finished_at).getTime() : 0;
  if (!start || !end) return t("progress.lastRoundUnknown", { when: whenLabel(r.finished_at ?? r.started_at) });
  return t("progress.lastRound", {
    when: whenLabel(r.finished_at),
    duration: fmtDuration(Math.max(1, Math.round((end - start) / 1000))),
    done: finished,
    total: r.stages.length,
  });
}

function Round({ round, updatedAt }: { round: RoundData; updatedAt: number }) {
  const { t } = useTranslation();
  const source =
    round.source === "manual" ? "progress.roundManual"
      : round.source === "command" ? "progress.roundCommand"
        : "progress.roundCron";
  return (
    <div>
      <h3 className="mb-2 flex flex-wrap items-baseline gap-x-2 text-xs font-bold uppercase tracking-wider text-muted">
        {t(source)}
        {round.started_at && (
          <span className="font-semibold normal-case tracking-normal">
            · {t("progress.startedAt", { time: clock(round.started_at) })}
          </span>
        )}
      </h3>
      <ul className="space-y-2">
        {round.stages.map((s) => (
          <li key={s.id}>
            <StageCard stage={s} updatedAt={updatedAt} />
          </li>
        ))}
      </ul>
    </div>
  );
}

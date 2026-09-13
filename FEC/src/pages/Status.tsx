import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { apiClient } from "../api/client";
import { Skeleton } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";
import { Operations, type OperationsData } from "../components/ops/Operations";
import { RunTimeline, type Run } from "../components/ops/RunTimeline";
import { LiveActivity, type Job, type Reanalysis } from "../components/ops/LiveActivity";
import { EvalsPanel, type EvalRun } from "../components/ops/EvalsPanel";
import { PipelineQueue, type Budget, type QueueData } from "../components/ops/PipelineQueue";

interface Stage {
  key: string;
  label: string;
  done: number;
  pending: number;
  failed: number;
  total: number;
  pct: number;
  scopes?: { scope: string; label: string; done: number; total: number; pct: number }[];
}

interface StatusPayload {
  operations?: OperationsData & {
    history?: Run[];
    activity?: Job[];
    reanalysis?: Reanalysis | null;
    evals?: EvalRun[];
  };
  queue?: QueueData;
  budget?: Budget | null;
  totals: Record<string, number>;
  stages: Stage[];
  jobs: { id: number; kind: string; status: string; progress: number; message: string }[];
  accounts: { username: string; owner_type: string; reels: number; last_scraped_at: string | null }[];
  last: Record<string, string | null>;
}

async function fetchStatus(): Promise<StatusPayload> {
  const { data } = await apiClient.get("/ops/status/");
  return data;
}

/** Operational dashboard: how far each pipeline stage has got, refreshed on
 *  its own so a long backlog can be watched without reloading. */
export default function Status() {
  const { t } = useTranslation();
  const { data, isLoading, dataUpdatedAt, refetch, isFetching } = useQuery({
    queryKey: ["ops-status"],
    queryFn: fetchStatus,
    refetchInterval: 5000,
  });

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-4 sm:px-6">
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-heading">{t("status.title")}</h1>
            <p className="text-sm text-muted">
              {t("status.subtitle")}
              {dataUpdatedAt
                ? ` · ${t("status.updatedAt")} ${new Date(dataUpdatedAt).toLocaleTimeString("it-IT")}`
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
            {t("status.refresh")}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
          <div className="mx-auto max-w-4xl space-y-6">
            {isLoading || !data ? (
              <Skeleton className="h-64" />
            ) : (
              <>
                {/* What is moving right now — first, because it is the
                    question the page is opened to answer. */}
                <LiveActivity
                  jobs={data.operations?.activity ?? []}
                  reanalysis={data.operations?.reanalysis}
                  updatedAt={dataUpdatedAt}
                />

                {/* How much is left, how long it takes, and the button that
                    starts it — above the stage bars, because "quanto manca"
                    is asked before "a che punto è". */}
                <PipelineQueue
                  queue={data.queue}
                  job={data.jobs.find((j) => j.kind === "pipeline")}
                  budget={data.budget}
                  onStarted={() => refetch()}
                />

                {/* Totals */}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    ["reels", t("status.reels")],
                    ["active", t("status.active")],
                    ["arguments", t("status.arguments")],
                    ["clusters", t("status.clusters")],
                  ].map(([k, label]) => (
                    <div key={k} className="rounded-xl border border-border bg-surface p-4 shadow-card">
                      <div className="text-xs font-bold uppercase tracking-wider text-muted">{label}</div>
                      <div className="mt-1 text-2xl font-bold text-navy tabular-nums">
                        {data.totals[k] ?? 0}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Stage progress */}
                <section>
                  <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
                    {t("status.stages")}
                  </h2>
                  <div className="space-y-3">
                    {data.stages.map((s) => (
                      <div key={s.key} className="rounded-xl border border-border bg-surface p-4 shadow-card">
                        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                          <span className="text-sm font-bold text-navy">{s.label}</span>
                          <span className="text-xs font-semibold tabular-nums text-muted">
                            {s.done}/{s.total} · {s.pct}%
                            {s.pending > 0 && ` · ${s.pending} ${t("status.pending")}`}
                            {s.failed > 0 && (
                              <span className="text-danger"> · {s.failed} {t("status.failed")}</span>
                            )}
                          </span>
                        </div>
                        <div className="h-2 w-full overflow-hidden rounded-full bg-white">
                          <div
                            className={
                              "h-full rounded-full transition-all duration-700 " +
                              (s.pct >= 100 ? "bg-success" : "bg-secondary")
                            }
                            style={{ width: `${Math.max(s.pct, 1)}%` }}
                          />
                        </div>

                        {/* Whose content the percentage is made of. Without
                            this, a figure driven entirely by the competitor
                            backlog reads as if Medyca's own reels were
                            missing. */}
                        {s.scopes && s.scopes.length > 1 && (
                          <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1">
                            {s.scopes.map((sc) => (
                              <span
                                key={sc.scope}
                                className="flex items-center gap-1.5 text-xs text-muted"
                              >
                                <span
                                  className={
                                    "h-1.5 w-1.5 rounded-full " +
                                    (sc.scope === "owned" ? "bg-secondary" : "bg-warning")
                                  }
                                  aria-hidden
                                />
                                {sc.label}
                                <span className="font-semibold tabular-nums text-navy">
                                  {sc.done}/{sc.total}
                                </span>
                                <span className="tabular-nums">· {sc.pct}%</span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </section>

                {/* How long each run took */}
                <section>
                  <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                    {t("ops.timeline")}
                  </h2>
                  <p className="mb-3 text-xs text-muted/80">{t("ops.timelineHint")}</p>
                  <RunTimeline
                    runs={data.operations?.history ?? []}
                    updatedAt={dataUpdatedAt}
                  />
                </section>

                {/* Evals: quality as a number, run over run */}
                <section>
                  <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                    Evals
                  </h2>
                  <p className="mb-3 text-xs text-muted/80">{t("evals.hint")}</p>
                  <EvalsPanel runs={data.operations?.evals ?? []} />
                </section>

                {/* Running jobs */}
                <section>
                  <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
                    {t("status.jobs")}
                  </h2>
                  {data.jobs.length === 0 ? (
                    <p className="text-sm text-muted">{t("status.noJobs")}</p>
                  ) : (
                    <div className="space-y-2">
                      {data.jobs.map((j) => (
                        <div key={j.id} className="rounded-xl border border-border bg-surface p-3 shadow-card">
                          <div className="flex justify-between gap-3 text-sm">
                            <span className="font-semibold text-navy">{j.kind}</span>
                            <span className="tabular-nums text-muted">{j.progress}%</span>
                          </div>
                          <div className="truncate text-xs text-muted">{j.message}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                {/* What is running right now */}
                <Operations data={data.operations} />

                {/* Accounts */}
                <section>
                  <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
                    {t("status.accounts")}
                  </h2>
                  <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
                    <table className="w-full min-w-[440px] text-sm">
                      <thead className="bg-surface text-left text-xs font-bold uppercase tracking-wider text-muted">
                        <tr>
                          <th className="px-4 py-2.5">{t("status.account")}</th>
                          <th className="px-4 py-2.5 text-right">{t("status.reels")}</th>
                          <th className="px-4 py-2.5">{t("status.lastScrape")}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {data.accounts.map((a) => (
                          <tr key={a.username} className="text-navy">
                            <td className="px-4 py-2.5">
                              @{a.username}
                              <span className="ml-2 text-xs text-muted">{a.owner_type}</span>
                            </td>
                            <td className="px-4 py-2.5 text-right tabular-nums">{a.reels}</td>
                            <td className="px-4 py-2.5 text-xs text-muted">
                              {a.last_scraped_at
                                ? new Date(a.last_scraped_at).toLocaleString("it-IT")
                                : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </>
            )}
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

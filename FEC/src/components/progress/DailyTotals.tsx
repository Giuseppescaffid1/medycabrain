import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchDaily } from "../../api/progress";
import { Skeleton } from "../ui/primitives";
import { PanelError } from "../manage/parts";
import { fmtDuration } from "../ops/live";
import { fmtNum } from "./format";

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/**
 * "Oggi": machine hours per kind of process. The local model has no price in
 * euro; what it costs is the time the machine is busy, so that is the number.
 * One generation uses the whole machine, so seconds are never multiplied by
 * the number of cores. Asked once, then every 60 s.
 */
export function DailyTotals() {
  const { t } = useTranslation();
  const [day, setDay] = useState(() => new Date());
  const key = iso(day);
  const isToday = key === iso(new Date());
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["ops-llm", key],
    queryFn: () => fetchDaily(key),
    refetchInterval: isToday ? 60000 : false,
  });

  const shift = (n: number) => {
    const d = new Date(day);
    d.setDate(d.getDate() + n);
    setDay(d);
  };
  const max = Math.max(1, ...(data?.by_process ?? []).map((p) => p.machine_seconds));

  return (
    <section>
      <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
        {t("progress.today")}
      </h2>
      <p className="mb-3 text-xs text-muted/80">{t("progress.todayHint")}</p>

      <div className="mb-3 flex items-center gap-2">
        <button
          onClick={() => shift(-1)}
          aria-label={t("progress.prevDay")}
          className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-white text-secondary transition duration-200 hover:bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary"
        >
          <span aria-hidden>‹</span>
        </button>
        <span className="min-w-[9rem] text-center text-sm font-bold text-navy" aria-live="polite">
          {isToday ? t("progress.today") : day.toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "long" })}
        </span>
        <button
          onClick={() => shift(1)}
          disabled={isToday}
          aria-label={t("progress.nextDay")}
          className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-white text-secondary transition duration-200 hover:bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary disabled:opacity-40"
        >
          <span aria-hidden>›</span>
        </button>
      </div>

      {isLoading ? (
        <Skeleton className="h-40" />
      ) : isError || !data ? (
        <PanelError message={t("progress.dayError")} onRetry={() => refetch()} />
      ) : (
        <div className="space-y-2">
          {data.by_process.length === 0 ? (
            <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted shadow-card">
              {t("progress.dayEmpty")}
            </p>
          ) : (
            <>
              {data.by_process.map((p) => (
                <div key={p.process} className="rounded-xl border border-border bg-surface p-4 shadow-card">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                    <span className="min-w-0 text-sm font-bold text-navy">{p.label}</span>
                    <span className="text-sm font-bold tabular-nums text-navy">
                      {t("progress.machineTime", { duration: fmtDuration(p.machine_seconds) })}
                    </span>
                  </div>
                  <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-white" aria-hidden>
                    <div
                      className="h-full rounded-full bg-secondary"
                      style={{ width: `${Math.max(Math.round((p.machine_seconds / max) * 100), 1)}%` }}
                    />
                  </div>
                  <p className="mt-2 text-xs tabular-nums text-muted">
                    {t("progress.calls", { n: p.calls })}
                    {p.wait_seconds > 0 && ` · ${t("progress.waitedFor", { duration: fmtDuration(p.wait_seconds) })}`}
                    {(p.tokens_in > 0 || p.tokens_out > 0) &&
                      ` · ${t("progress.tokensInOut", { tin: fmtNum(p.tokens_in, 0), tout: fmtNum(p.tokens_out, 0) })}`}
                    {p.failed > 0 && ` · ${t("progress.failedCalls", { n: p.failed })}`}
                  </p>
                </div>
              ))}
              <p className="flex justify-between gap-3 px-1 text-sm font-bold tabular-nums text-navy">
                <span>{t("progress.total")}</span>
                <span>{fmtDuration(data.total_machine_seconds)}</span>
              </p>
            </>
          )}

          <div className="rounded-xl border border-border bg-white p-4 shadow-card">
            <div className="text-sm font-bold text-navy">{t("progress.remoteTitle")}</div>
            <p className="mt-1 text-xs tabular-nums text-muted">
              {t("progress.remoteLine", {
                calls: data.remote.calls,
                tokens: fmtNum(data.remote.tokens_in + data.remote.tokens_out, 0),
                duration: fmtDuration(data.remote.seconds),
              })}
            </p>
          </div>

          <p className="px-1 text-xs text-muted">
            {data.speed.tokens_per_second != null
              ? t("progress.speedLine", { n: fmtNum(data.speed.tokens_per_second), model: data.speed.model })
              : t("progress.speedNone")}
          </p>
        </div>
      )}
    </section>
  );
}

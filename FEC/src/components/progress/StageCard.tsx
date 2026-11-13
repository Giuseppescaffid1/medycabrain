import { useTranslation } from "react-i18next";
import { Badge } from "../ui/primitives";
import type { StageData } from "../../api/progress";
import { elapsedNow, fmtDuration } from "../ops/live";
import { ModelLines } from "./ModelLines";
import { clock, fmtNum } from "./format";

/**
 * One stage of a round, in the shape of a tqdm line.
 *
 * "Stile tqdm" means the same four numbers in the same order — done/total,
 * speed, elapsed, remaining — not a bar made of characters, which would not
 * fit in 380 px. Waiting and finished stages are a single short line so nine
 * stages and one open card fit on a phone; only the running (or failed) stage
 * opens up.
 *
 * Nothing is invented: before 3 items there is no measured speed, so the page
 * shows the rate of earlier rounds and says so, or a dash. A stage that never
 * declared its total shows "In corso da N min" and no bar, like tqdm without
 * a total.
 */
export function StageCard({ stage, updatedAt }: { stage: StageData; updatedAt?: number }) {
  const { t } = useTranslation();
  const processed = stage.done + stage.failed + stage.skipped;
  const hasTotal = stage.total != null && stage.total > 0;
  // A failed stage has already closed its current phase into `phases`: do not
  // say it twice ("Fase: download · download 12/40").
  const earlier = stage.phases.filter((p) => p.phase !== stage.phase);

  if (stage.status === "waiting") {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-white px-4 py-2.5 text-sm">
        <span className="min-w-0 truncate font-semibold text-navy/80">{stage.label}</span>
        <span className="shrink-0 text-xs text-muted">{t("progress.waiting")}</span>
      </div>
    );
  }

  if (stage.status === "done") {
    const secs = stage.phases.length
      ? stage.phases.reduce((n, p) => n + p.seconds, 0)
      : stage.elapsed_seconds;
    return (
      <div className="rounded-xl border border-border bg-white px-4 py-2.5 text-sm">
        <div className="flex items-start justify-between gap-3">
          <span className="flex min-w-0 items-center gap-2 font-semibold text-navy">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden className="shrink-0 text-success">
              <path d="M3 8.5l3.2 3L13 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="truncate">{stage.label}</span>
            <span className="sr-only">{t("progress.done")}</span>
          </span>
          <span className="shrink-0 text-right text-xs tabular-nums text-muted">
            {hasTotal
              ? t("progress.doneLine", {
                  done: stage.done + stage.skipped, total: stage.total,
                  duration: fmtDuration(Math.round(secs)),
                })
              : t("progress.doneLineNoTotal", { duration: fmtDuration(Math.round(secs)) })}
          </span>
        </div>
        {(stage.failed > 0 || stage.skipped > 0 || stage.note) && (
          <div className="mt-1 text-xs text-muted">
            {stage.failed > 0 && <span className="font-semibold text-warning">{t("progress.failedItems", { n: stage.failed })}</span>}
            {stage.failed > 0 && stage.note && " · "}
            {stage.note}
          </div>
        )}
      </div>
    );
  }

  const failed = stage.status === "failed";
  const pct = hasTotal ? Math.min(100, Math.round((processed / (stage.total as number)) * 100)) : 0;
  const elapsed = elapsedNow(stage.phase_seconds || stage.elapsed_seconds, failed ? undefined : updatedAt);
  const whoKey = stage.who === "stt" && stage.current?.who ? "" : `progress.who.${stage.who}`;
  const who = whoKey ? t(whoKey) : (stage.current?.who ?? "");

  return (
    <article
      className={
        "rounded-xl border p-4 shadow-card " +
        (failed ? "border-danger/30 bg-danger/5" : "border-secondary/30 bg-secondary/5")
      }
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {failed ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden className="shrink-0 text-danger">
            <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.6" />
            <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        ) : (
          <span className="h-2 w-2 shrink-0 rounded-full bg-success motion-safe:animate-pulse" aria-hidden />
        )}
        <h3 className="min-w-0 text-sm font-bold text-navy">{stage.label}</h3>
        <span className={"text-xs font-bold " + (failed ? "text-danger" : "text-secondary")}>
          {failed ? t("progress.failed") : t("progress.running")}
        </span>
        {who && <Badge className="ml-auto bg-white text-secondary">{who}</Badge>}
      </div>

      {stage.phase && (
        <p className="mt-1.5 text-xs text-muted">
          {t("progress.phase")}: <span className="font-semibold text-navy">{stage.phase}</span>
          {earlier.length > 0 && (
            <span>
              {" · "}
              {earlier
                .map((p) => `${p.phase} ${p.done + p.skipped}/${p.total ?? "?"}`)
                .join(" · ")}
            </span>
          )}
        </p>
      )}

      {failed && (
        <p role="alert" className="mt-2 text-sm font-semibold text-danger">
          {stage.interrupted
            ? t("progress.interrupted", { time: clock(stage.finished_at) })
            : stage.error}
        </p>
      )}

      {hasTotal ? (
        <>
          <div
            role="progressbar"
            aria-label={stage.label}
            aria-valuemin={0}
            aria-valuemax={stage.total as number}
            aria-valuenow={processed}
            className="mt-3 h-2 w-full overflow-hidden rounded-full bg-white"
          >
            <div
              className={
                "h-full rounded-full motion-safe:transition-all motion-safe:duration-700 " +
                (failed ? "bg-muted" : "bg-secondary")
              }
              style={{ width: `${Math.max(pct, 1)}%` }}
            />
          </div>

          {failed ? (
            <p className="mt-2 text-xs text-muted">
              {t("progress.failedBefore", { done: stage.done, total: stage.total })}
            </p>
          ) : (
            <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Box label={t("progress.box.done")}>
                {processed}/{stage.total}
                <small className="block text-xs font-normal text-muted">
                  {stage.unit}
                  {stage.failed > 0 && ` · ${t("progress.failedItems", { n: stage.failed })}`}
                </small>
              </Box>
              <Box label={t("progress.box.speed")}>
                {stage.rate_per_minute != null
                  ? t("progress.perMinute", { n: fmtNum(stage.rate_per_minute) })
                  : "—"}
                <small className="block text-xs font-normal text-muted">
                  {stage.rate_source === "previous" && t("progress.speedPrevious")}
                  {stage.tokens_per_second != null &&
                    t("progress.tokensPerSecond", { n: fmtNum(stage.tokens_per_second) })}
                </small>
              </Box>
              <Box label={t("progress.box.elapsed")}>{fmtDuration(Math.round(elapsed))}</Box>
              <Box label={t("progress.box.left")}>
                {stage.eta_seconds != null
                  ? t("progress.roughly", { duration: fmtDuration(stage.eta_seconds) })
                  : "—"}
                <small className="block text-xs font-normal text-muted">
                  {stage.eta_seconds != null && t("progress.inThisRound")}
                </small>
              </Box>
            </dl>
          )}
        </>
      ) : (
        !failed && (
          <p className="mt-2 text-sm font-semibold text-navy tabular-nums">
            {t("progress.runningNoTotal", { duration: fmtDuration(Math.round(elapsed)) })}
          </p>
        )
      )}

      {stage.note && <p className="mt-2 text-xs text-muted">{stage.note}</p>}

      {!failed && stage.items.length === 0 && stage.current && stage.current.label && (
        <p className="mt-3 truncate rounded-lg bg-white px-3 py-2 text-xs text-muted">
          {t("progress.workingOn")}:{" "}
          <span className="font-semibold text-navy">{stage.current.label}</span>
        </p>
      )}
      {!failed && <ModelLines items={stage.items} more={stage.items_more} updatedAt={updatedAt} />}
    </article>
  );
}

function Box({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-white px-3 py-2">
      <dt className="text-[10px] font-bold uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-bold tabular-nums text-navy">{children}</dd>
    </div>
  );
}

import { useTranslation } from "react-i18next";
import { Badge, Skeleton } from "../ui/primitives";

/**
 * What is actually running, read from the machine at request time: the
 * crontab as installed, systemd's own view of each service, the last time
 * each pipeline stage finished, and which model serves which job.
 *
 * Deliberately not a written description — a page that lists a schedule from
 * memory keeps reassuring the reader about a job that was changed weeks ago.
 */
export interface OperationsData {
  services: { unit: string; label: string; state: string }[];
  schedules: { what: string; stage: string; when: string; niced: boolean }[];
  last_runs: { stage: string; label: string; at: string; seconds: number; result: string }[];
  models: { task: string; model: string; why: string }[];
  provider: string;
}

const fmtDuration = (s: number) =>
  s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;

const fmtWhen = (iso: string) => {
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 60) return `${mins} min fa`;
  if (mins < 60 * 36) return `${Math.round(mins / 60)} h fa`;
  return d.toLocaleDateString("it-IT", { day: "numeric", month: "short" });
};

export function Operations({ data }: { data?: OperationsData }) {
  const { t } = useTranslation();
  if (!data) return <Skeleton className="h-64" />;

  return (
    <div className="space-y-6">
      {/* Services */}
      <section>
        <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
          {t("ops.services")}
        </h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {data.services.map((s) => {
            const up = s.state === "active";
            return (
              <div
                key={s.unit}
                className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3 shadow-card"
              >
                <div className="min-w-0">
                  <div className="text-sm font-bold text-navy">{s.label}</div>
                  <div className="truncate text-xs text-muted">{s.unit}</div>
                </div>
                <Badge className={up ? "bg-success/10 text-success" : "bg-danger/10 text-danger"}>
                  <span
                    className={"mr-1.5 inline-block h-1.5 w-1.5 rounded-full " +
                      (up ? "bg-success" : "bg-danger")}
                  />
                  {up ? t("ops.up") : s.state}
                </Badge>
              </div>
            );
          })}
        </div>
      </section>

      {/* Schedules */}
      <section>
        <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
          {t("ops.schedules")}
        </h2>
        <p className="mb-3 text-xs text-muted/80">{t("ops.schedulesHint")}</p>
        <div className="space-y-2">
          {data.schedules.map((c, i) => (
            <div
              key={i}
              className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface px-4 py-3 shadow-card"
            >
              <Badge className="bg-secondary/10 text-secondary">{c.when}</Badge>
              <span className="min-w-0 flex-1 text-sm text-navy">{c.what}</span>
              {c.niced && (
                <Badge className="bg-white text-muted">{t("ops.lowPriority")}</Badge>
              )}
            </div>
          ))}
          {data.schedules.length === 0 && (
            <p className="text-sm text-muted">{t("ops.noSchedules")}</p>
          )}
        </div>
      </section>

      {/* Last runs */}
      <section>
        <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
          {t("ops.lastRuns")}
        </h2>
        <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
          <table className="w-full min-w-[520px] text-sm">
            <thead className="bg-surface text-left text-xs font-bold uppercase tracking-wider text-muted">
              <tr>
                <th className="px-4 py-2.5">{t("ops.stage")}</th>
                <th className="px-4 py-2.5">{t("ops.when")}</th>
                <th className="px-4 py-2.5 text-right">{t("ops.duration")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.last_runs.map((r) => (
                <tr key={r.stage} className="text-navy">
                  <td className="px-4 py-2.5 font-semibold">{r.label}</td>
                  <td className="px-4 py-2.5 text-muted">{fmtWhen(r.at)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                    {fmtDuration(r.seconds)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Models */}
      <section>
        <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
          {t("ops.models")}
        </h2>
        <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
          <table className="w-full min-w-[560px] text-sm">
            <tbody className="divide-y divide-border">
              {data.models.map((m) => (
                <tr key={m.task} className="align-top">
                  <td className="w-56 px-4 py-3 font-semibold text-navy">{m.task}</td>
                  <td className="w-52 px-4 py-3">
                    <Badge className="bg-surface text-heading">{m.model}</Badge>
                  </td>
                  <td className="px-4 py-3 text-muted">{m.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

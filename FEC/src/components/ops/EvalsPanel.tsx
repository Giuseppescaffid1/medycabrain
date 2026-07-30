import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../ui/primitives";

/**
 * The evaluation scorecards, read from the suite's own output files.
 *
 * Quality became a measured number on 2026-07-30 (manage.py eval_mcp):
 * golden questions over the real HTTPS path, ownership checked against the
 * database on every hit, quotes verified verbatim, an LLM judge for
 * relevance. This panel shows the latest run and the trend — the whole
 * point is that a change to retrieval moves a number here, visibly.
 */
export interface EvalRun {
  at: string;
  metrics: Record<string, number | string>;
  latency_ms: Record<string, { p50: number; max: number; n: number }>;
  cases: { name: string; pass: boolean; detail: string }[];
  passed: number;
  total: number;
}

const METRIC_LABELS: Record<string, string> = {
  hit_rate_golden: "Hit rate (domande d'oro)",
  ownership_accuracy: "Proprietà corretta",
  groundedness: "Citazioni verificate",
  judge_relevance: "Pertinenza (giudice 0-2)",
};

const pct = (v: number | string | undefined) =>
  typeof v === "number" ? `${Math.round(v * 100)}%` : "—";

const fmtAt = (iso: string) =>
  new Date(iso).toLocaleString("it-IT", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });

export function EvalsPanel({ runs }: { runs: EvalRun[] }) {
  const { t } = useTranslation();
  const [showCases, setShowCases] = useState(false);
  if (!runs?.length) {
    return (
      <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted shadow-card">
        {t("evals.empty")}
      </p>
    );
  }
  const latest = runs[0];
  const prev = runs[1];

  const delta = (key: string) => {
    const a = prev?.metrics?.[key];
    const b = latest.metrics?.[key];
    if (typeof a !== "number" || typeof b !== "number" || a === b) return null;
    const up = b > a;
    return (
      <span className={"ml-1.5 text-xs font-bold " + (up ? "text-success" : "text-danger")}>
        {up ? "↑" : "↓"}
      </span>
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-bold text-navy">
          {t("evals.lastRun")} · {fmtAt(latest.at)}
        </span>
        <Badge
          className={
            latest.passed === latest.total
              ? "bg-success/10 text-success"
              : "bg-warning/10 text-warning"
          }
        >
          {latest.passed}/{latest.total} {t("evals.casesPassed")}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Object.entries(METRIC_LABELS).map(([key, label]) => {
          const v = latest.metrics?.[key];
          const display =
            key === "judge_relevance"
              ? (typeof v === "number" ? v.toFixed(2) : "—")
              : pct(v);
          return (
            <div key={key} className="rounded-xl border border-border bg-surface p-4 shadow-card">
              <div className="text-xs font-bold uppercase tracking-wider text-muted">
                {label}
              </div>
              <div className="mt-1 text-2xl font-bold tabular-nums text-navy">
                {display}
                {delta(key)}
              </div>
            </div>
          );
        })}
      </div>

      {latest.latency_ms?.cerca && (
        <p className="text-xs text-muted">
          {t("evals.latency", {
            p50: latest.latency_ms.cerca.p50,
            max: latest.latency_ms.cerca.max,
          })}
        </p>
      )}

      <button
        onClick={() => setShowCases((v) => !v)}
        className="text-xs font-semibold text-secondary underline-offset-2 hover:underline"
      >
        {showCases ? t("evals.hideCases") : t("evals.showCases")}
      </button>
      {showCases && (
        <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {latest.cases.map((c) => (
            <li
              key={c.name}
              className="flex items-center gap-2 rounded-xl border border-border bg-white px-3 py-2 text-xs shadow-card"
            >
              <span className={c.pass ? "text-success" : "text-danger"} aria-hidden>
                {c.pass ? "✓" : "✗"}
              </span>
              <span className="min-w-0 flex-1 truncate font-semibold text-navy">
                {c.name}
              </span>
              {c.detail && <span className="shrink-0 text-muted">{c.detail}</span>}
            </li>
          ))}
        </ul>
      )}

      {runs.length > 1 && (
        <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
          <table className="w-full min-w-[520px] text-xs">
            <thead className="bg-surface text-left font-bold uppercase tracking-wider text-muted">
              <tr>
                <th className="px-3 py-2">{t("evals.run")}</th>
                <th className="px-3 py-2 text-right">Hit</th>
                <th className="px-3 py-2 text-right">{t("evals.ownership")}</th>
                <th className="px-3 py-2 text-right">{t("evals.grounded")}</th>
                <th className="px-3 py-2 text-right">{t("evals.judge")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {runs.map((r) => (
                <tr key={r.at} className="tabular-nums text-navy">
                  <td className="px-3 py-2">{fmtAt(r.at)}</td>
                  <td className="px-3 py-2 text-right">{pct(r.metrics?.hit_rate_golden)}</td>
                  <td className="px-3 py-2 text-right">{pct(r.metrics?.ownership_accuracy)}</td>
                  <td className="px-3 py-2 text-right">{pct(r.metrics?.groundedness)}</td>
                  <td className="px-3 py-2 text-right">
                    {typeof r.metrics?.judge_relevance === "number"
                      ? (r.metrics.judge_relevance as number).toFixed(2)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

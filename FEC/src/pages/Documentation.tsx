import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Badge, Button } from "../components/ui/primitives";
import { PageTransition, staggerContainer, staggerItem } from "../components/ui/motion";
import { FlowCanvas } from "../components/docs/FlowCanvas";
import { Operations, type OperationsData } from "../components/ops/Operations";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";

const DRAWIO = "/docs/medycabrain-pipeline-cliente.drawio";

/** The five stages, in the same words the client-facing diagram uses. */
const STAGES = [
  { n: "1", key: "collect", icon: "📥" },
  { n: "2", key: "understand", icon: "🎧" },
  { n: "3", key: "organise", icon: "🧭" },
  { n: "4", key: "advise", icon: "🧠" },
] as const;

export default function Documentation() {
  const { t } = useTranslation();
  // Read live rather than written down: a documented schedule drifts, and then
  // reassures the reader about a job that was changed weeks ago.
  const ops = useQuery({
    queryKey: ["ops-status"],
    queryFn: async () => (await apiClient.get("/ops/status/")).data as { operations: OperationsData },
    refetchInterval: 30000,
  });

  const inputs = t("docs.inputs.items", { returnObjects: true }) as string[];
  const outputs = t("docs.outputs.items", { returnObjects: true }) as string[];

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-4 py-4 sm:px-6">
          <h1 className="text-xl font-bold text-heading">{t("docs.title")}</h1>
          <p className="text-sm text-muted">{t("docs.subtitle")}</p>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6">
          <div className="mx-auto max-w-5xl space-y-8">
            {/* ── What goes in ─────────────────────────────────────── */}
            <section>
              <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
                {t("docs.inputs.title")}
              </h2>
              <div className="flex flex-wrap gap-2">
                {inputs.map((label) => (
                  <span
                    key={label}
                    className="rounded-full border border-border bg-surface px-4 py-2 text-sm font-semibold text-navy"
                  >
                    {label}
                  </span>
                ))}
              </div>
            </section>

            {/* ── The four stages ──────────────────────────────────── */}
            <section>
              <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
                {t("docs.flow.title")}
              </h2>
              <motion.ol
                variants={staggerContainer}
                initial="initial"
                animate="animate"
                className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
              >
                {STAGES.map((s) => (
                  <motion.li key={s.key} variants={staggerItem} className="h-full">
                    <div className="flex h-full flex-col gap-2 rounded-xl border border-border bg-surface p-4 shadow-card">
                      <div className="flex items-center gap-2">
                        <span className="text-xl" aria-hidden>{s.icon}</span>
                        <span className="text-xs font-bold uppercase tracking-wider text-secondary">
                          {s.n} · {t(`docs.flow.${s.key}.title`)}
                        </span>
                      </div>
                      <p className="text-sm text-navy">{t(`docs.flow.${s.key}.body`)}</p>
                    </div>
                  </motion.li>
                ))}
              </motion.ol>
              <p className="mt-3 rounded-xl border border-border bg-white p-4 text-sm text-navy shadow-card">
                {t("docs.weighting")}
              </p>
              <p className="mt-2 text-xs font-semibold text-success">{t("docs.nightly")}</p>
            </section>

            {/* ── The flow, as a node graph ────────────────────────── */}
            <section>
              <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                {t("flow.title")}
              </h2>
              <p className="mb-3 text-xs text-muted/80">{t("flow.hint")}</p>
              <FlowCanvas />
            </section>

            {/* ── What you get ─────────────────────────────────────── */}
            <section>
              <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
                {t("docs.outputs.title")}
              </h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {outputs.map((label) => (
                  <div
                    key={label}
                    className="rounded-xl border border-border bg-surface p-4 text-sm font-semibold text-navy shadow-card"
                  >
                    {label}
                  </div>
                ))}
              </div>
            </section>

            {/* ── What is running right now, read from the machine ── */}
            <section>
              <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                {t("ops.title")}
              </h2>
              <p className="mb-3 text-xs text-muted/80">{t("ops.subtitle")}</p>
              <Operations data={ops.data?.operations} />
            </section>

            {/* ── Which model does what ───────────────────────────── */}
            <section>
              <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                {t("docs.models.title")}
              </h2>
              <p className="mb-3 text-xs text-muted/80">{t("docs.models.hint")}</p>
              <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
                <table className="w-full min-w-[620px] text-sm">
                  <tbody className="divide-y divide-border">
                    {(t("docs.models.items", { returnObjects: true }) as
                      { step: string; model: string; why: string }[]).map((m) => (
                      <tr key={m.step} className="align-top">
                        <td className="w-48 px-4 py-3 font-semibold text-navy">{m.step}</td>
                        <td className="w-44 px-4 py-3">
                          <Badge className="bg-surface text-heading">{m.model}</Badge>
                        </td>
                        <td className="px-4 py-3 text-muted">{m.why}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {/* ── How the RAG answers ─────────────────────────────── */}
            <section>
              <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
                {t("docs.rag.title")}
              </h2>
              <ol className="space-y-2">
                {(t("docs.rag.steps", { returnObjects: true }) as string[]).map((step, i) => (
                  <li key={step} className="flex gap-3 rounded-xl border border-border bg-surface p-3 shadow-card">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary/15 text-xs font-bold text-secondary">
                      {i + 1}
                    </span>
                    <span className="text-sm text-navy">{step}</span>
                  </li>
                ))}
              </ol>
            </section>

            {/* ── Known limits: say it before the client discovers it ── */}
            <section>
              <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
                {t("docs.limits.title")}
              </h2>
              <ul className="space-y-2">
                {(t("docs.limits.items", { returnObjects: true }) as string[]).map((l) => (
                  <li key={l} className="rounded-xl border border-border bg-white p-3 text-sm text-navy shadow-card">
                    {l}
                  </li>
                ))}
              </ul>
            </section>

            {/* ── Downloads ────────────────────────────────────────── */}
            <section>
              <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
                {t("docs.download.title")}
              </h2>
              <p className="mb-3 text-xs text-muted/80">{t("docs.download.hint")}</p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <a href={DRAWIO} download>
                  <Button variant="primary" className="w-full sm:w-auto">
                    ⬇ {t("docs.download.drawio")}
                  </Button>
                </a>
                <a href="https://app.diagrams.net/" target="_blank" rel="noreferrer">
                  <Button variant="secondary" className="w-full sm:w-auto">
                    ↗ {t("docs.download.open")}
                  </Button>
                </a>
              </div>
            </section>
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

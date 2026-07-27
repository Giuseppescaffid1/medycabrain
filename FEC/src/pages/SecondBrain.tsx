import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import { fetchCoverageMap } from "../api/strategy";
import { fetchIdeas, updateIdeaStatus, type ContentIdea } from "../api/secondBrain";
import { useJobs } from "../contexts/JobsContext";
import { Button, EmptyState, Skeleton, fieldCls } from "../components/ui/primitives";
import { IdeaCard } from "../components/plan/IdeaCard";
import { useCopy } from "../lib/clipboard";
import { PageTransition, staggerContainer, staggerItem } from "../components/ui/motion";

/**
 * The editorial plan: contents ready to be filmed, not a prose brief.
 *
 * Each entry is grounded in material that exists — an idea whose sources could
 * not be resolved never reaches this screen — so the client can check where a
 * suggestion comes from before spending a shoot on it.
 */
export default function SecondBrain() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { jobs, startPlan } = useJobs();
  const [n, setN] = useState(6);
  const [theme, setTheme] = useState("");
  const { copy, state: copyState } = useCopy();

  const coverage = useQuery({ queryKey: ["coverage-map"], queryFn: fetchCoverageMap });
  const ideas = useQuery({ queryKey: ["ideas"], queryFn: () => fetchIdeas() });
  const building = jobs.some(
    (j) => j.kind === "editorial" && (j.status === "queued" || j.status === "running")
  );

  // Optimistic: the card leaves (or gets its badge) the instant it is clicked.
  // Waiting for the refetch made the list re-order under the cursor, so only
  // the top card felt clickable.
  const setStatus = useMutation({
    mutationFn: (v: { id: number; status: "saved" | "dismissed" }) =>
      updateIdeaStatus(v.id, v.status),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: ["ideas"] });
      const before = qc.getQueryData<ContentIdea[]>(["ideas"]);
      qc.setQueryData<ContentIdea[]>(["ideas"], (old) =>
        (old ?? []).map((i) => (i.id === v.id ? { ...i, status: v.status } : i))
      );
      return { before };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.before) qc.setQueryData(["ideas"], ctx.before);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["ideas"] }),
  });

  const visible = (ideas.data ?? []).filter((i) => i.status !== "dismissed");

  const exportPlan = () => {
    const md = visible
      .map(
        (i) =>
          `## ${i.argument_it}\n\n` +
          `**${t("plan.hook")}:** ${i.hook_it}\n\n` +
          `**${t("plan.angle")}:** ${i.angle_it}\n\n` +
          `**${t("plan.why")}:** ${i.rationale_it}\n\n` +
          `**${t("plan.sources")}:** ${(i.source_refs ?? []).map((s) => s.title).join(", ")}\n`
      )
      .join("\n---\n\n");
    copy(`# ${t("plan.title")}\n\n${md}`);
  };

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-4 pb-4 pt-5 sm:px-6">
          <h1 className="text-xl font-bold text-heading">{t("plan.title")}</h1>
          <p className="text-sm text-muted">{t("plan.subtitle")}</p>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6">
          <div className="mx-auto max-w-4xl space-y-7">
            {/* ── Generate ─────────────────────────────────────────── */}
            <section className="rounded-2xl border border-border bg-surface p-4 shadow-card">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <label className="flex-1">
                  <span className="mb-1 block text-xs font-bold uppercase tracking-wider text-muted">
                    {t("plan.themeLabel")}
                  </span>
                  <input
                    value={theme}
                    onChange={(e) => setTheme(e.target.value)}
                    placeholder={t("plan.themePlaceholder")}
                    className={fieldCls + " w-full"}
                  />
                </label>
                <label className="w-full sm:w-32">
                  <span className="mb-1 block text-xs font-bold uppercase tracking-wider text-muted">
                    {t("plan.n")}
                  </span>
                  <select
                    value={n}
                    onChange={(e) => setN(Number(e.target.value))}
                    className={fieldCls + " w-full"}
                  >
                    {[4, 6, 8, 10].map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                </label>
                <Button
                  variant="primary"
                  loading={building}
                  onClick={() => startPlan(n, theme.trim())}
                  className="shrink-0"
                >
                  {t("plan.generate")}
                </Button>
              </div>
              {building && <p className="mt-2 text-xs text-muted">{t("plan.generating")}</p>}
            </section>

            {/* ── Coverage: the bridge from the data to the plan ───── */}
            <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="rounded-2xl border border-border bg-surface p-4 shadow-card">
                <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-navy">
                  <span className="h-2 w-2 rounded-full bg-success" /> {t("sb.covered")}
                </h2>
                <div className="flex flex-wrap gap-2">
                  {coverage.isLoading && <Skeleton className="h-8 w-40" />}
                  {coverage.data?.covered.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => startPlan(n, c.label)}
                      className="rounded-full border border-border bg-white px-3 py-1.5 text-sm font-semibold text-navy transition hover:border-success"
                    >
                      {c.custom && "👤 "}
                      {c.label} <span className="text-xs text-muted/80">· {c.reels + c.docs}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="rounded-2xl border border-border bg-surface p-4 shadow-card">
                <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-navy">
                  <span className="h-2 w-2 rounded-full bg-warning" /> {t("sb.opportunities")}
                </h2>
                <div className="flex flex-wrap gap-2">
                  {coverage.isLoading && <Skeleton className="h-8 w-40" />}
                  {coverage.data?.opportunities.map((o) => (
                    <button
                      key={o.id}
                      onClick={() => startPlan(n, o.label)}
                      className="rounded-full border border-warning/40 bg-warning/10 px-3 py-1.5 text-sm font-semibold text-warning transition hover:border-warning"
                    >
                      {o.custom && "👤 "}
                      {o.label} <span className="text-xs text-warning/70">· {o.reels}</span>
                    </button>
                  ))}
                </div>
              </div>
            </section>

            {/* ── The plan ─────────────────────────────────────────── */}
            <section>
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="text-xs font-bold uppercase tracking-wider text-muted">
                  {t("plan.title")} {visible.length > 0 ? `· ${visible.length}` : ""}
                </h2>
                {visible.length > 0 && (
                  <Button variant="secondary" onClick={exportPlan}>
                    {copyState === "done" ? `✓ ${t("plan.copied")}` : `📋 ${t("plan.export")}`}
                  </Button>
                )}
              </div>
              {ideas.isLoading ? (
                <Skeleton className="h-48" />
              ) : visible.length === 0 ? (
                <EmptyState message={t("plan.empty")} />
              ) : (
                <motion.div
                  variants={staggerContainer}
                  initial="initial"
                  animate="animate"
                  className="flex flex-col gap-3"
                >
                  <AnimatePresence initial={false}>
                    {visible.map((idea) => (
                      <motion.div
                        key={idea.id}
                        layout
                        variants={staggerItem}
                        exit={{ opacity: 0, x: 24, height: 0, marginBottom: -12 }}
                        transition={{ duration: 0.26 }}
                      >
                        <IdeaCard
                          idea={idea}
                          onSave={() => setStatus.mutate({ id: idea.id, status: "saved" })}
                          onDismiss={() => setStatus.mutate({ id: idea.id, status: "dismissed" })}
                        />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </motion.div>
              )}
            </section>
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

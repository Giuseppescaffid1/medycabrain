import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  fetchBriefs,
  fetchCoverageMap,
  updateBriefStatus,
  type StrategyBrief,
} from "../api/strategy";
import { useJobs } from "../contexts/JobsContext";
import { Badge, Button, EmptyState, Skeleton, fieldCls } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";

/**
 * Second Brain = motore di strategia contenuti. L'utente scrive un tema (o
 * clicca un'opportunità dalla mappa di copertura); il motore risponde con un
 * brief fondato su cosa Medyca ha già + il gap vs competitor, pesato per
 * engagement. Da ogni brief si genera una bozza completa on-demand.
 */
export default function SecondBrain() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { jobs, startStrategy, startDraft } = useJobs();
  const [input, setInput] = useState("");

  const coverage = useQuery({ queryKey: ["coverage-map"], queryFn: fetchCoverageMap });
  const briefs = useQuery({ queryKey: ["briefs"], queryFn: fetchBriefs });
  const analyzing = jobs.some((j) => j.kind === "strategy" && (j.status === "queued" || j.status === "running"));

  const setStatus = useMutation({
    mutationFn: (v: { id: number; status: "saved" | "dismissed" }) => updateBriefStatus(v.id, v.status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["briefs"] }),
  });

  const run = (text: string, kind = "input") => {
    if (text.trim().length >= 3) startStrategy(text.trim(), kind);
  };

  return (
    <PageTransition>
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 pb-4 pt-5 sm:px-6">
        <h1 className="text-xl font-bold text-heading">{t("sb.title")}</h1>
        <p className="text-sm text-muted">{t("sb.subtitle")}</p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6">
        <div className="mx-auto max-w-4xl space-y-8">
          {/* ── Input box ─────────────────────────────────────────── */}
          <div>
            <form
              onSubmit={(e) => { e.preventDefault(); run(input); }}
              className="flex flex-col gap-3"
            >
              <label className="text-sm font-semibold text-navy">{t("sb.inputLabel")}</label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={t("sb.inputPlaceholder")}
                  className={fieldCls + " h-12 min-w-0 flex-1 rounded-2xl text-base"}
                />
                <Button type="submit" disabled={input.trim().length < 3} loading={analyzing} className="h-12 shrink-0">
                  {t("sb.analyze")}
                </Button>
              </div>
              <p className="text-xs text-muted/80">{t("sb.inputHint")}</p>
            </form>
          </div>

          {/* ── Coverage map ──────────────────────────────────────── */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-navy">
                <span className="h-2 w-2 rounded-full bg-success" /> {t("sb.covered")}
              </h2>
              <p className="mb-3 text-xs text-muted/80">{t("sb.coveredHint")}</p>
              <div className="flex flex-wrap gap-2">
                {coverage.data?.covered.map((c) => (
                  <button key={c.id} onClick={() => run(c.label, "theme")}
                    className="rounded-full border border-border bg-white px-3 py-1.5 text-sm font-semibold text-navy transition hover:border-success">
                    {c.custom && <span title="Tema del cliente">👤 </span>}{c.label} <span className="text-xs text-muted/80">· {c.reels + c.docs}</span>
                  </button>
                ))}
                {coverage.data && coverage.data.covered.length === 0 && (
                  <span className="text-xs text-muted/80">—</span>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-navy">
                <span className="h-2 w-2 rounded-full bg-warning" /> {t("sb.opportunities")}
              </h2>
              <p className="mb-3 text-xs text-muted/80">{t("sb.opportunitiesHint")}</p>
              <div className="flex flex-wrap gap-2">
                {coverage.data?.opportunities.map((o) => (
                  <button key={o.id} onClick={() => run(o.label, "theme")}
                    className="rounded-full border border-warning/40 bg-warning/10 px-3 py-1.5 text-sm font-semibold text-warning transition hover:border-warning">
                    {o.custom && <span title="Tema del cliente">👤 </span>}{o.label} <span className="text-xs text-warning/70">· {o.reels}</span>
                  </button>
                ))}
                {coverage.data && coverage.data.opportunities.length === 0 && (
                  <span className="text-xs text-muted/80">—</span>
                )}
              </div>
            </div>
          </div>

          {/* ── Briefs ────────────────────────────────────────────── */}
          <div>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
              {t("sb.briefs")}
            </h2>
            {briefs.isLoading ? (
              <Skeleton className="h-40" />
            ) : !briefs.data || briefs.data.length === 0 ? (
              <EmptyState message={t("sb.noBriefs")} />
            ) : (
              <div className="flex flex-col gap-3">
                {briefs.data.map((b) => (
                  <BriefCard
                    key={b.id}
                    brief={b}
                    onDraft={() => startDraft(b.id)}
                    drafting={jobs.some((j) => j.kind === "strategy_draft" && (j.status === "queued" || j.status === "running"))}
                    onSave={() => setStatus.mutate({ id: b.id, status: "saved" })}
                    onDismiss={() => setStatus.mutate({ id: b.id, status: "dismissed" })}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
    </PageTransition>
  );
}

const COVERAGE_BADGE: Record<string, string> = {
  covered: "bg-success/10 text-success",
  partial: "bg-secondary/10 text-secondary",
  gap: "bg-warning/10 text-warning",
};

function BriefCard({
  brief,
  onDraft,
  drafting,
  onSave,
  onDismiss,
}: {
  brief: StrategyBrief;
  onDraft: () => void;
  drafting: boolean;
  onSave: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"brief" | "draft">("brief");

  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge className={COVERAGE_BADGE[brief.coverage]}>{t(`sb.cov.${brief.coverage}`)}</Badge>
        {brief.status === "saved" && <Badge className="bg-success/10 text-success">{t("sb.saved")}</Badge>}
        {(tab === "draft" ? brief.draft_model : brief.brief_model) && (
          <Badge className="bg-white text-muted">
            🤖 {tab === "draft" ? brief.draft_model : brief.brief_model}
          </Badge>
        )}
        <span className="text-xs font-semibold text-muted">
          {t("sb.mSources", { m: brief.medyca_sources.length, c: brief.competitor_sources.length })}
        </span>
      </div>
      <h3 className="text-base font-bold text-heading">{brief.input_text}</h3>

      {brief.draft_md && (
        <div className="mt-2 inline-flex rounded-full border border-border bg-white p-0.5">
          <TabBtn active={tab === "brief"} onClick={() => setTab("brief")}>{t("sb.tabBrief")}</TabBtn>
          <TabBtn active={tab === "draft"} onClick={() => setTab("draft")}>{t("sb.tabDraft")}</TabBtn>
        </div>
      )}

      <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-navy">
        {tab === "draft" && brief.draft_md ? brief.draft_md : brief.brief_md}
      </div>

      {/* sources */}
      {(brief.medyca_sources.length > 0 || brief.competitor_sources.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {brief.medyca_sources.map((s, i) => (
            <a key={`m${i}`} href={s.url} target="_blank" rel="noreferrer">
              <Badge className="bg-success/10 text-success">
                {s.kind === "blog" ? "📄" : "🎬"} {s.title.slice(0, 32)}{s.weight ? ` · ${s.weight}×` : ""}
              </Badge>
            </a>
          ))}
          {brief.competitor_sources.map((s, i) => (
            <a key={`c${i}`} href={s.url} target="_blank" rel="noreferrer">
              <Badge className="bg-warning/10 text-warning">🏷 {s.title.slice(0, 30)}</Badge>
            </a>
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {!brief.draft_md && (
          <Button variant="secondary" onClick={onDraft} loading={drafting}>
            ✍️ {t("sb.genDraft")}
          </Button>
        )}
        <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(tab === "draft" ? brief.draft_md : brief.brief_md)}>
          📋 {t("sb.copy")}
        </Button>
        <Button variant="ghost" onClick={onSave}>⭐ {t("sb.save")}</Button>
        <Button variant="ghost" onClick={onDismiss}>✕ {t("sb.dismiss")}</Button>
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={"rounded-full px-3 py-1 text-xs font-semibold transition " + (active ? "bg-secondary text-white" : "text-muted hover:text-navy")}
    >
      {children}
    </button>
  );
}

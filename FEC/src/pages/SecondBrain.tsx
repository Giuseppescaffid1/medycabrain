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
import { Badge, Button, EmptyState, Spinner } from "../components/ui/primitives";

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
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 pb-4 pt-5">
        <h1 className="text-xl font-bold text-white">{t("sb.title")}</h1>
        <p className="text-sm text-zinc-500">{t("sb.subtitle")}</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-4xl space-y-8">
          {/* ── Input box ─────────────────────────────────────────── */}
          <div>
            <form
              onSubmit={(e) => { e.preventDefault(); run(input); }}
              className="flex flex-col gap-3"
            >
              <label className="text-sm font-medium text-zinc-300">{t("sb.inputLabel")}</label>
              <div className="flex gap-2">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={t("sb.inputPlaceholder")}
                  className="flex-1 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 text-base text-white outline-none focus:border-indigo-500"
                />
                <Button type="submit" disabled={analyzing || input.trim().length < 3}>
                  {analyzing ? t("sb.analyzing") : t("sb.analyze")}
                </Button>
              </div>
              <p className="text-xs text-zinc-600">{t("sb.inputHint")}</p>
            </form>
          </div>

          {/* ── Coverage map ──────────────────────────────────────── */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-300">
                <span className="h-2 w-2 rounded-full bg-emerald-500" /> {t("sb.covered")}
              </h2>
              <p className="mb-3 text-xs text-zinc-600">{t("sb.coveredHint")}</p>
              <div className="flex flex-wrap gap-2">
                {coverage.data?.covered.map((c) => (
                  <button key={c.id} onClick={() => run(c.label, "theme")}
                    className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-300 hover:border-emerald-600/60">
                    {c.label} <span className="text-xs text-zinc-600">· {c.reels + c.docs}</span>
                  </button>
                ))}
                {coverage.data && coverage.data.covered.length === 0 && (
                  <span className="text-xs text-zinc-600">—</span>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-300">
                <span className="h-2 w-2 rounded-full bg-amber-500" /> {t("sb.opportunities")}
              </h2>
              <p className="mb-3 text-xs text-zinc-600">{t("sb.opportunitiesHint")}</p>
              <div className="flex flex-wrap gap-2">
                {coverage.data?.opportunities.map((o) => (
                  <button key={o.id} onClick={() => run(o.label, "theme")}
                    className="rounded-lg border border-amber-700/40 bg-amber-950/30 px-3 py-1.5 text-sm text-amber-200 hover:border-amber-500/70">
                    {o.label} <span className="text-xs text-amber-700">· {o.reels}</span>
                  </button>
                ))}
                {coverage.data && coverage.data.opportunities.length === 0 && (
                  <span className="text-xs text-zinc-600">—</span>
                )}
              </div>
            </div>
          </div>

          {/* ── Briefs ────────────────────────────────────────────── */}
          <div>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
              {t("sb.briefs")}
            </h2>
            {briefs.isLoading ? (
              <Spinner />
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
  );
}

const COVERAGE_BADGE: Record<string, string> = {
  covered: "bg-emerald-600/20 text-emerald-300",
  partial: "bg-indigo-600/20 text-indigo-300",
  gap: "bg-amber-600/20 text-amber-300",
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
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge className={COVERAGE_BADGE[brief.coverage]}>{t(`sb.cov.${brief.coverage}`)}</Badge>
        {brief.status === "saved" && <Badge className="bg-emerald-600/20 text-emerald-300">{t("sb.saved")}</Badge>}
        <span className="text-xs text-zinc-500">
          {t("sb.mSources", { m: brief.medyca_sources.length, c: brief.competitor_sources.length })}
        </span>
      </div>
      <h3 className="text-base font-semibold text-white">{brief.input_text}</h3>

      {brief.draft_md && (
        <div className="mt-2 inline-flex rounded-lg border border-zinc-800 bg-zinc-950 p-0.5">
          <TabBtn active={tab === "brief"} onClick={() => setTab("brief")}>{t("sb.tabBrief")}</TabBtn>
          <TabBtn active={tab === "draft"} onClick={() => setTab("draft")}>{t("sb.tabDraft")}</TabBtn>
        </div>
      )}

      <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
        {tab === "draft" && brief.draft_md ? brief.draft_md : brief.brief_md}
      </div>

      {/* sources */}
      {(brief.medyca_sources.length > 0 || brief.competitor_sources.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {brief.medyca_sources.map((s, i) => (
            <a key={`m${i}`} href={s.url} target="_blank" rel="noreferrer">
              <Badge className="bg-emerald-600/15 text-emerald-300">
                {s.kind === "blog" ? "📄" : "🎬"} {s.title.slice(0, 32)}{s.weight ? ` · ${s.weight}×` : ""}
              </Badge>
            </a>
          ))}
          {brief.competitor_sources.map((s, i) => (
            <a key={`c${i}`} href={s.url} target="_blank" rel="noreferrer">
              <Badge className="bg-amber-600/15 text-amber-300">🏷 {s.title.slice(0, 30)}</Badge>
            </a>
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {!brief.draft_md && (
          <Button variant="ghost" onClick={onDraft} disabled={drafting}>
            {drafting ? t("sb.drafting") : `✍️ ${t("sb.genDraft")}`}
          </Button>
        )}
        <Button variant="ghost" onClick={() => navigator.clipboard?.writeText(tab === "draft" ? brief.draft_md : brief.brief_md)}>
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
      className={"rounded-md px-3 py-1 text-xs font-medium " + (active ? "bg-indigo-600 text-white" : "text-zinc-400")}
    >
      {children}
    </button>
  );
}

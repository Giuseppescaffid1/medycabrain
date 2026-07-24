import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  askKnowledge,
  fetchKnowledgeDocs,
  searchKnowledge,
  type AskResult,
  type KnowledgeHit,
} from "../api/knowledge";
import { fetchReels } from "../api/endpoints";
import { Badge, Button, EmptyState, Skeleton, Spinner, fieldCls } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";
import { useDebounced } from "../lib/useDebounced";
import { formatCount, formatDate } from "../lib/utils";

/**
 * The visible knowledge bank: every Medyca asset the second brain draws on —
 * blog articles + reels (with transcripts) — browsable and searchable. This is
 * the "see the knowledge bank properly" view the client asked for.
 */
type Tab = "browse" | "search" | "ask";

export default function KnowledgeBank() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("browse");

  const tabs: { key: Tab; label: string; icon: string }[] = [
    { key: "browse", label: t("kb.browse"), icon: "📚" },
    { key: "search", label: t("kb.search"), icon: "🔎" },
    { key: "ask", label: t("kb.ask"), icon: "💬" },
  ];

  return (
    <PageTransition>
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 pb-4 pt-5 sm:px-6">
        <h1 className="text-xl font-bold text-heading">{t("kb.title")}</h1>
        <p className="text-sm text-muted">{t("kb.subtitle")}</p>
        <div className="mt-4 inline-flex rounded-full border border-border bg-white p-1">
          {tabs.map((m) => (
            <button
              key={m.key}
              onClick={() => setTab(m.key)}
              className={
                "flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-semibold transition " +
                (tab === m.key ? "bg-secondary text-white" : "text-muted hover:text-navy")
              }
            >
              <span>{m.icon}</span>
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6">
        {tab === "browse" && <BrowseTab />}
        {tab === "search" && <SearchTab />}
        {tab === "ask" && <AskTab />}
      </div>
    </div>
    </PageTransition>
  );
}

// ── Browse: blog articles + Medyca reels, the raw knowledge ──────────────
function BrowseTab() {
  const { t } = useTranslation();
  const docs = useQuery({ queryKey: ["kb-docs"], queryFn: () => fetchKnowledgeDocs() });
  const reels = useQuery({
    queryKey: ["kb-reels"],
    queryFn: () => fetchReels({ scope: "medyca", ordering: "-posted_at", page_size: 200 }),
  });

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted">
          📄 {t("kb.articles")} <span className="text-muted/70">({docs.data?.length ?? 0})</span>
        </h2>
        {docs.isLoading ? <Skeleton className="h-40" /> : (docs.data?.length ?? 0) === 0 ? (
          <EmptyState message={t("kb.noDocs")} />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {docs.data!.map((d) => (
              <a key={d.id} href={d.source_url} target="_blank" rel="noreferrer"
                className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4 shadow-card transition duration-200 hover:-translate-y-0.5 hover:border-secondary hover:shadow-float">
                <div className="flex items-center gap-2">
                  <Badge className="bg-success/10 text-success">blog</Badge>
                  <span className="text-xs text-muted">{formatDate(d.published_at)}</span>
                </div>
                <h3 className="font-bold text-heading">{d.title.replace(/ — Medyca$/, "")}</h3>
                {d.summary_it && <p className="line-clamp-2 text-sm text-muted">{d.summary_it}</p>}
                {d.topics?.length > 0 && (
                  <div className="mt-auto flex flex-wrap gap-1.5">
                    {d.topics.slice(0, 4).map((tp) => <Badge key={tp}>{tp}</Badge>)}
                  </div>
                )}
              </a>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted">
          🎬 {t("kb.reels")} <span className="text-muted/70">({reels.data?.count ?? 0})</span>
        </h2>
        {reels.isLoading ? <Skeleton className="h-64" /> : (
          <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="bg-surface text-left text-xs font-bold uppercase tracking-wider text-muted">
                <tr>
                  <th className="px-4 py-2.5">{t("kb.content")}</th>
                  <th className="px-4 py-2.5">{t("kb.date")}</th>
                  <th className="px-4 py-2.5 text-right">{t("kb.views")}</th>
                  <th className="px-4 py-2.5">{t("kb.transcript")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {reels.data?.results.map((r) => (
                  <tr key={r.id} className="text-navy">
                    <td className="max-w-md px-4 py-2.5">
                      <a href={`https://www.instagram.com/reel/${r.shortcode}/`} target="_blank" rel="noreferrer"
                        className="line-clamp-1 hover:text-secondary">
                        {r.summary_it || r.caption || r.shortcode}
                      </a>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted">{formatDate(r.posted_at)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{formatCount(r.view_count)}</td>
                    <td className="px-4 py-2.5">
                      {r.transcribe_status === "done"
                        ? <Badge className="bg-success/10 text-success">✓</Badge>
                        : <span className="text-xs text-muted/70">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function SearchTab() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 350);
  const res = useQuery({
    queryKey: ["kb-search", debounced],
    queryFn: () => searchKnowledge(debounced, 10),
    enabled: debounced.trim().length > 2,
  });
  return (
    <div className="mx-auto max-w-3xl">
      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t("kb.searchPlaceholder")}
        className={fieldCls + " h-12 w-full rounded-2xl text-base"}
      />
      <div className="mt-5">
        {debounced.trim().length <= 2 ? <EmptyState message={t("kb.searchHint")} /> :
          res.isLoading ? <Skeleton className="h-40" /> : <HitList hits={res.data ?? []} />}
      </div>
    </div>
  );
}

function AskTab() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const ask = useMutation<AskResult, unknown, string>({ mutationFn: (query) => askKnowledge(query) });
  return (
    <div className="mx-auto max-w-3xl">
      <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask.mutate(q.trim()); }} className="flex flex-col gap-3">
        <textarea
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("kb.askPlaceholder")}
          rows={3}
          className="w-full resize-none rounded-2xl border border-border bg-white px-4 py-3 text-sm text-navy outline-none transition placeholder:text-muted/70 focus:border-secondary"
        />
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={q.trim().length < 3} loading={ask.isPending}>
            {t("kb.askButton")}
          </Button>
          <span className="text-xs text-muted/80">{t("kb.askNote")}</span>
        </div>
      </form>
      {ask.isPending && <div className="mt-6"><Spinner label={t("kb.thinking")} /></div>}
      {ask.data && (
        <div className="mt-6 flex flex-col gap-4">
          <div className="rounded-xl border border-secondary/40 bg-surface p-5 shadow-card">
            <p className="whitespace-pre-wrap text-sm text-navy">{ask.data.answer}</p>
          </div>
          <div>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-muted">{t("kb.sources")}</h3>
            <HitList hits={ask.data.sources} numbered />
          </div>
        </div>
      )}
    </div>
  );
}

function HitList({ hits, numbered }: { hits: KnowledgeHit[]; numbered?: boolean }) {
  const { t } = useTranslation();
  if (hits.length === 0) return <EmptyState message={t("kb.noResults")} />;
  return (
    <div className="flex flex-col gap-3">
      {hits.map((h, i) => (
        <a key={`${h.kind}-${h.id}`} href={h.url} target="_blank" rel="noreferrer"
          className="flex gap-3 rounded-xl border border-border bg-surface p-4 shadow-card transition duration-200 hover:border-secondary hover:shadow-float">
          {numbered && (
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary/15 text-xs font-bold text-secondary">
              {i + 1}
            </span>
          )}
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex items-center gap-2">
              <Badge className={h.kind === "blog" ? "bg-success/10 text-success" : "bg-secondary/10 text-secondary"}>
                {h.kind === "blog" ? "blog" : "reel"}
              </Badge>
              <span className="text-xs text-muted/80">{t("kb.relevance")} {(h.score * 100).toFixed(0)}%</span>
            </div>
            <h3 className="font-bold text-heading">{h.title.replace(/ — Medyca$/, "")}</h3>
            <p className="line-clamp-2 text-sm text-muted">{h.summary || h.snippet}</p>
          </div>
        </a>
      ))}
    </div>
  );
}

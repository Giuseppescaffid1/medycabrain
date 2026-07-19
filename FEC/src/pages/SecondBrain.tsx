import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  fetchIdeas,
  generateIdeas,
  updateIdeaStatus,
  type ContentIdea,
} from "../api/secondBrain";
import {
  askKnowledge,
  fetchKnowledgeDocs,
  searchKnowledge,
  type AskResult,
  type KnowledgeHit,
} from "../api/knowledge";
import { Badge, Button, EmptyState, Spinner } from "../components/ui/primitives";
import { useDebounced } from "../lib/useDebounced";
import { formatDate } from "../lib/utils";

type Tab = "ideas" | "browse" | "search" | "ask";

export default function SecondBrain() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("ideas");

  const tabs: { key: Tab; label: string }[] = [
    { key: "ideas", label: t("sb.ideas") },
    { key: "browse", label: t("sb.browse") },
    { key: "search", label: t("sb.searchTab") },
    { key: "ask", label: t("sb.ask") },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-xl font-bold text-white">{t("sb.title")}</h1>
        <p className="text-sm text-zinc-500">{t("sb.subtitle")}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {tabs.map((tb) => (
            <button
              key={tb.key}
              onClick={() => setTab(tb.key)}
              className={
                "rounded-lg px-3 py-1.5 text-sm font-medium transition " +
                (tab === tb.key
                  ? "bg-indigo-600/30 text-indigo-200 ring-1 ring-indigo-500"
                  : "bg-zinc-900 text-zinc-400 hover:text-zinc-200")
              }
            >
              {tb.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {tab === "ideas" && <IdeasTab />}
        {tab === "browse" && <BrowseTab />}
        {tab === "search" && <SearchTab />}
        {tab === "ask" && <AskTab />}
      </div>
    </div>
  );
}

// ── Content ideas ────────────────────────────────────────────────────────
function IdeasTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const ideas = useQuery({ queryKey: ["ideas"], queryFn: () => fetchIdeas() });
  const generate = useMutation({
    mutationFn: () => generateIdeas(8),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ideas"] }),
  });
  const setStatus = useMutation({
    mutationFn: (v: { id: number; status: "saved" | "dismissed" }) =>
      updateIdeaStatus(v.id, v.status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ideas"] }),
  });

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-5 flex items-center justify-between gap-4">
        <p className="text-sm text-zinc-500">{t("sb.ideasIntro")}</p>
        <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
          {generate.isPending ? t("sb.generating") : t("sb.generate")}
        </Button>
      </div>
      {generate.isPending && <Spinner label={t("sb.generating")} />}
      {generate.isError && <p className="text-sm text-red-400">{t("common.error")}</p>}

      {ideas.isLoading ? (
        <Spinner />
      ) : !ideas.data || ideas.data.length === 0 ? (
        <EmptyState message={t("sb.noIdeas")} />
      ) : (
        <div className="flex flex-col gap-3">
          {ideas.data.map((idea) => (
            <IdeaCard
              key={idea.id}
              idea={idea}
              onSave={() => setStatus.mutate({ id: idea.id, status: "saved" })}
              onDismiss={() => setStatus.mutate({ id: idea.id, status: "dismissed" })}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function IdeaCard({
  idea,
  onSave,
  onDismiss,
}: {
  idea: ContentIdea;
  onSave: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        {idea.is_gap && <Badge className="bg-amber-600/20 text-amber-300">{t("sb.gap")}</Badge>}
        {idea.status === "saved" && (
          <Badge className="bg-emerald-600/20 text-emerald-300">{t("sb.saved")}</Badge>
        )}
      </div>
      <h3 className="text-base font-semibold text-white">{idea.argument_it}</h3>
      {idea.rationale_it && <p className="mt-1 text-sm text-zinc-400">{idea.rationale_it}</p>}
      {idea.angle_it && (
        <p className="mt-2 text-sm text-indigo-300">
          <span className="font-semibold">{t("sb.angle")}:</span> {idea.angle_it}
        </p>
      )}
      {idea.source_refs?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {idea.source_refs.map((s, i) => (
            <a key={i} href={s.url} target="_blank" rel="noreferrer">
              <Badge className="bg-zinc-800 text-zinc-400 hover:text-zinc-200">
                {s.kind === "blog" ? "📄" : "🎬"} {s.title.replace(/ — Medyca$/, "").slice(0, 40)}
              </Badge>
            </a>
          ))}
        </div>
      )}
      <div className="mt-3 flex gap-2">
        <Button variant="ghost" onClick={onSave}>⭐ {t("sb.save")}</Button>
        <Button variant="ghost" onClick={onDismiss}>✕ {t("sb.dismiss")}</Button>
      </div>
    </div>
  );
}

// ── Browse / Search / Ask over the knowledge bank ────────────────────────
function BrowseTab() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 400);
  const docs = useQuery({ queryKey: ["kb-docs", debounced], queryFn: () => fetchKnowledgeDocs(debounced) });
  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t("sb.filterPlaceholder")}
        className="mb-5 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm text-white outline-none focus:border-indigo-500"
      />
      {docs.isLoading ? <Spinner /> :
        !docs.data || docs.data.length === 0 ? <EmptyState message={t("sb.noDocs")} /> :
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {docs.data.map((d) => (
            <a key={d.id} href={d.source_url} target="_blank" rel="noreferrer"
              className="flex flex-col gap-2 rounded-xl border border-zinc-800 bg-zinc-900 p-4 transition hover:border-indigo-600/60">
              <div className="flex items-center gap-2">
                <Badge className="bg-emerald-600/20 text-emerald-300">blog</Badge>
                <span className="text-xs text-zinc-500">{formatDate(d.published_at)}</span>
              </div>
              <h3 className="font-semibold text-white">{d.title.replace(/ — Medyca$/, "")}</h3>
              {d.summary_it && <p className="line-clamp-2 text-sm text-zinc-400">{d.summary_it}</p>}
              {d.topics?.length > 0 && (
                <div className="mt-auto flex flex-wrap gap-1.5">
                  {d.topics.slice(0, 4).map((tp) => <Badge key={tp}>{tp}</Badge>)}
                </div>
              )}
            </a>
          ))}
        </div>}
    </div>
  );
}

function SearchTab() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 400);
  const res = useQuery({
    queryKey: ["kb-search", debounced],
    queryFn: () => searchKnowledge(debounced),
    enabled: debounced.trim().length > 2,
  });
  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t("sb.searchPlaceholder")}
        className="mb-5 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm text-white outline-none focus:border-indigo-500"
      />
      {debounced.trim().length <= 2 ? <EmptyState message={t("sb.searchHint")} /> :
        res.isLoading ? <Spinner /> : <HitList hits={res.data ?? []} />}
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
          placeholder={t("sb.askPlaceholder")}
          rows={3}
          className="w-full resize-none rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm text-white outline-none focus:border-indigo-500"
        />
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={ask.isPending || q.trim().length < 3}>
            {ask.isPending ? t("sb.thinking") : t("sb.askButton")}
          </Button>
          <span className="text-xs text-zinc-600">{t("sb.askNote")}</span>
        </div>
      </form>
      {ask.isPending && <div className="mt-6"><Spinner label={t("sb.thinking")} /></div>}
      {ask.isError && <p className="mt-6 text-sm text-red-400">{t("common.error")}</p>}
      {ask.data && (
        <div className="mt-6 flex flex-col gap-4">
          <div className="rounded-xl border border-indigo-600/40 bg-indigo-600/10 p-5">
            <p className="whitespace-pre-wrap text-sm text-zinc-100">{ask.data.answer}</p>
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">{t("sb.sources")}</h3>
            <HitList hits={ask.data.sources} numbered />
          </div>
        </div>
      )}
    </div>
  );
}

function HitList({ hits, numbered }: { hits: KnowledgeHit[]; numbered?: boolean }) {
  const { t } = useTranslation();
  if (hits.length === 0) return <EmptyState message={t("sb.noResults")} />;
  return (
    <div className="flex flex-col gap-3">
      {hits.map((h, i) => (
        <a key={`${h.kind}-${h.id}`} href={h.url} target="_blank" rel="noreferrer"
          className="flex gap-3 rounded-xl border border-zinc-800 bg-zinc-900 p-4 transition hover:border-indigo-600/60">
          {numbered && (
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-600/30 text-xs font-semibold text-indigo-200">
              {i + 1}
            </span>
          )}
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Badge className={h.kind === "blog" ? "bg-emerald-600/20 text-emerald-300" : "bg-pink-600/20 text-pink-300"}>
                {h.kind === "blog" ? "blog" : "reel"}
              </Badge>
              <span className="text-xs text-zinc-600">{t("sb.relevance")} {(h.score * 100).toFixed(0)}%</span>
            </div>
            <h3 className="font-semibold text-white">{h.title.replace(/ — Medyca$/, "")}</h3>
            <p className="line-clamp-2 text-sm text-zinc-400">{h.summary || h.snippet}</p>
          </div>
        </a>
      ))}
    </div>
  );
}

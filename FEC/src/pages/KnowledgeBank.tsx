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
import { Badge, Button, EmptyState, Spinner } from "../components/ui/primitives";
import { useDebounced } from "../lib/useDebounced";
import { formatDate } from "../lib/utils";

type Mode = "browse" | "search" | "ask";

export default function KnowledgeBank() {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("browse");
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query, 400);

  const docs = useQuery({
    queryKey: ["kb-docs", mode === "browse" ? debounced : ""],
    queryFn: () => fetchKnowledgeDocs(mode === "browse" ? debounced : ""),
    enabled: mode === "browse",
  });

  const search = useQuery({
    queryKey: ["kb-search", debounced],
    queryFn: () => searchKnowledge(debounced),
    enabled: mode === "search" && debounced.trim().length > 2,
  });

  const ask = useMutation<AskResult, unknown, string>({
    mutationFn: (q: string) => askKnowledge(q),
  });

  const tabs: { key: Mode; label: string }[] = [
    { key: "browse", label: t("kb.browse") },
    { key: "search", label: t("kb.search") },
    { key: "ask", label: t("kb.ask") },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-xl font-bold text-white">{t("kb.title")}</h1>
        <p className="text-sm text-zinc-500">{t("kb.subtitle")}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {tabs.map((tb) => (
            <button
              key={tb.key}
              onClick={() => setMode(tb.key)}
              className={
                "rounded-lg px-3 py-1.5 text-sm font-medium transition " +
                (mode === tb.key
                  ? "bg-indigo-600/30 text-indigo-200 ring-1 ring-indigo-500"
                  : "bg-zinc-900 text-zinc-400 hover:text-zinc-200")
              }
            >
              {tb.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 px-6 py-5">
        {mode !== "ask" && (
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={mode === "browse" ? t("kb.filterPlaceholder") : t("kb.searchPlaceholder")}
            className="mb-5 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm text-white outline-none focus:border-indigo-500"
          />
        )}

        {mode === "browse" && (
          docs.isLoading ? <Spinner /> :
          !docs.data || docs.data.length === 0 ? <EmptyState message={t("kb.empty")} /> :
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
          </div>
        )}

        {mode === "search" && (
          debounced.trim().length <= 2 ? <EmptyState message={t("kb.searchHint")} /> :
          search.isLoading ? <Spinner /> :
          <HitList hits={search.data ?? []} />
        )}

        {mode === "ask" && (
          <div className="mx-auto max-w-3xl">
            <form
              onSubmit={(e) => { e.preventDefault(); if (query.trim()) ask.mutate(query.trim()); }}
              className="flex flex-col gap-3"
            >
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("kb.askPlaceholder")}
                rows={3}
                className="w-full resize-none rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm text-white outline-none focus:border-indigo-500"
              />
              <div className="flex items-center gap-3">
                <Button type="submit" disabled={ask.isPending || query.trim().length < 3}>
                  {ask.isPending ? t("kb.thinking") : t("kb.askButton")}
                </Button>
                <span className="text-xs text-zinc-600">{t("kb.askNote")}</span>
              </div>
            </form>

            {ask.isPending && <div className="mt-6"><Spinner label={t("kb.thinking")} /></div>}
            {ask.isError && <p className="mt-6 text-sm text-red-400">{t("common.error")}</p>}
            {ask.data && (
              <div className="mt-6 flex flex-col gap-4">
                <div className="rounded-xl border border-indigo-600/40 bg-indigo-600/10 p-5">
                  <p className="whitespace-pre-wrap text-sm text-zinc-100">{ask.data.answer}</p>
                </div>
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                    {t("kb.sources")}
                  </h3>
                  <HitList hits={ask.data.sources} numbered />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
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
              <span className="text-xs text-zinc-600">{t("kb.relevance")} {(h.score * 100).toFixed(0)}%</span>
            </div>
            <h3 className="font-semibold text-white">{h.title.replace(/ — Medyca$/, "")}</h3>
            <p className="line-clamp-2 text-sm text-zinc-400">{h.summary || h.snippet}</p>
          </div>
        </a>
      ))}
    </div>
  );
}

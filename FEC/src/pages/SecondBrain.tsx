import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  fetchBlogDrafts,
  updateBlogDraftStatus,
  type BlogDraft,
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

type Mode = "search" | "ask" | "blog";

export default function SecondBrain() {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("search");

  const modes: { key: Mode; label: string; icon: string }[] = [
    { key: "search", label: t("sb.search"), icon: "🔎" },
    { key: "ask", label: t("sb.ask"), icon: "💬" },
    { key: "blog", label: t("sb.blog"), icon: "✍️" },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 pb-4 pt-5">
        <h1 className="text-xl font-bold text-white">{t("sb.title")}</h1>
        <p className="text-sm text-zinc-500">{t("sb.subtitle")}</p>
        <div className="mt-4 inline-flex rounded-xl border border-zinc-800 bg-zinc-900 p-1">
          {modes.map((m) => (
            <button
              key={m.key}
              onClick={() => setMode(m.key)}
              className={
                "flex items-center gap-2 rounded-lg px-4 py-1.5 text-sm font-medium transition " +
                (mode === m.key
                  ? "bg-indigo-600 text-white"
                  : "text-zinc-400 hover:text-zinc-200")
              }
            >
              <span>{m.icon}</span>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {mode === "search" && <SearchMode />}
        {mode === "ask" && <AskMode />}
        {mode === "blog" && <BlogMode />}
      </div>
    </div>
  );
}

// ── Search-first: semantic search with browse-when-empty ─────────────────
function SearchMode() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 350);
  const isSearching = debounced.trim().length > 2;

  const search = useQuery({
    queryKey: ["kb-search", debounced],
    queryFn: () => searchKnowledge(debounced, 8),
    enabled: isSearching,
  });
  const browse = useQuery({
    queryKey: ["kb-docs"],
    queryFn: () => fetchKnowledgeDocs(),
    enabled: !isSearching,
  });

  return (
    <div className="mx-auto max-w-3xl">
      <div className="relative">
        <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-lg text-zinc-500">🔎</span>
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("sb.searchPlaceholder")}
          className="w-full rounded-xl border border-zinc-700 bg-zinc-900 py-3.5 pl-12 pr-4 text-base text-white outline-none focus:border-indigo-500"
        />
      </div>
      <p className="mt-2 px-1 text-xs text-zinc-600">
        {isSearching ? t("sb.searchingIn") : t("sb.browseHint")}
      </p>

      <div className="mt-5">
        {isSearching ? (
          search.isLoading ? <Spinner /> : <HitList hits={search.data ?? []} />
        ) : browse.isLoading ? (
          <Spinner />
        ) : !browse.data || browse.data.length === 0 ? (
          <EmptyState message={t("sb.noDocs")} />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {browse.data.map((d) => (
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
      </div>
    </div>
  );
}

// ── Ask (RAG) ────────────────────────────────────────────────────────────
function AskMode() {
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
          className="w-full resize-none rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm text-white outline-none focus:border-indigo-500"
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

// ── Blog drafts (cluster-driven; generated from a cluster's page) ─────────
function BlogMode() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const drafts = useQuery({ queryKey: ["blog-drafts"], queryFn: () => fetchBlogDrafts() });

  const setStatus = useMutation({
    mutationFn: (v: { id: number; status: "saved" | "dismissed" }) => updateBlogDraftStatus(v.id, v.status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["blog-drafts"] }),
  });

  return (
    <div className="mx-auto max-w-4xl">
      <p className="mb-5 text-sm text-zinc-500">{t("sb.blogIntro")}</p>
      {drafts.isLoading ? (
        <Spinner />
      ) : !drafts.data || drafts.data.length === 0 ? (
        <EmptyState message={t("sb.noBlog")} />
      ) : (
        <div className="flex flex-col gap-3">
          {drafts.data.map((d) => (
            <BlogCard
              key={d.id}
              draft={d}
              onSave={() => setStatus.mutate({ id: d.id, status: "saved" })}
              onDismiss={() => setStatus.mutate({ id: d.id, status: "dismissed" })}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function BlogCard({ draft, onSave, onDismiss }: { draft: BlogDraft; onSave: () => void; onDismiss: () => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Badge className={draft.mode === "draft" ? "bg-amber-600/20 text-amber-300" : "bg-indigo-600/20 text-indigo-300"}>
          {draft.mode === "draft" ? t("blog.draft") : t("blog.expand")}
        </Badge>
        <span className="text-xs text-zinc-500">{t("blog.theme")}: {draft.cluster_label}</span>
        {draft.status === "saved" && <Badge className="bg-emerald-600/20 text-emerald-300">{t("sb.saved")}</Badge>}
      </div>
      <h3 className="text-base font-semibold text-white">{draft.title}</h3>
      <div className={"mt-2 whitespace-pre-wrap text-sm text-zinc-300 " + (open ? "" : "line-clamp-4")}>
        {draft.content_md}
      </div>
      <button onClick={() => setOpen((o) => !o)} className="mt-1 text-xs font-medium text-indigo-400">
        {open ? t("blog.collapse") : t("blog.readAll")}
      </button>
      {draft.source_refs?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {draft.source_refs.map((s, i) => (
            <a key={i} href={s.url} target="_blank" rel="noreferrer">
              <Badge className="bg-zinc-800 text-zinc-400 hover:text-zinc-200">
                {s.kind === "blog" ? "📄" : "🎬"} {s.title.replace(/ — Medyca$/, "").slice(0, 40)}
              </Badge>
            </a>
          ))}
        </div>
      )}
      <div className="mt-3 flex gap-2">
        <Button variant="ghost" onClick={() => navigator.clipboard?.writeText(draft.content_md)}>📋 {t("blog.copy")}</Button>
        <Button variant="ghost" onClick={onSave}>⭐ {t("sb.save")}</Button>
        <Button variant="ghost" onClick={onDismiss}>✕ {t("sb.dismiss")}</Button>
      </div>
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
          <div className="flex min-w-0 flex-col gap-1">
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

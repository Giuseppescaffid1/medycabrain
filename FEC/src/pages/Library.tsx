import { useMemo, useState } from "react";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { fetchReels, type ReelFilters, type Scope } from "../api/endpoints";
import { ReelCard } from "../components/reels/ReelCard";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { ArticleCard } from "../components/articles/ArticleCard";
import { ArticleDetailDrawer } from "../components/articles/ArticleDetailDrawer";
import { fetchKnowledgeDocs } from "../api/knowledge";
import { FilterBar } from "../components/filters/FilterBar";
import { StatBar } from "../components/layout/StatBar";
import { EmptyState, ErrorState, Skeleton, fieldCls } from "../components/ui/primitives";
import { LoadMore } from "../components/ui/LoadMore";
import { ScopeBadge } from "../components/ui/ScopeBadge";
import { PageTransition, staggerContainer, staggerItem } from "../components/ui/motion";
import { useDebounced } from "../lib/useDebounced";

export default function Library() {
  const { t } = useTranslation();
  const { scope: scopeParam } = useParams();
  const scope: Scope = scopeParam === "medyca" ? "medyca" : "competitor";
  const [filters, setFilters] = useState<ReelFilters>({ ordering: "-posted_at" });
  const [searchInput, setSearchInput] = useState("");
  const [openReel, setOpenReel] = useState<number | null>(null);
  const [openDoc, setOpenDoc] = useState<number | null>(null);
  const debouncedSearch = useDebounced(searchInput, 400);
  // Content type lives in the URL (?type=article): shareable and
  // reload-safe, without rewriting every route in the app.
  const [searchParams, setSearchParams] = useSearchParams();
  const contentType: "reel" | "article" =
    searchParams.get("type") === "article" ? "article" : "reel";
  const setContentType = (t2: "reel" | "article") =>
    setSearchParams(t2 === "article" ? { type: "article" } : {}, { replace: true });

  const effectiveFilters = useMemo(
    () => ({ ...filters, scope, search: debouncedSearch || undefined }),
    [filters, scope, debouncedSearch]
  );

  const reelsQuery = useInfiniteQuery({
    queryKey: ["reels", effectiveFilters],
    queryFn: ({ pageParam }) => fetchReels({ ...effectiveFilters, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.next ? allPages.length + 1 : undefined,
    enabled: contentType === "reel",
    // While the next keystroke loads, keep the previous results on screen:
    // without it every letter flashed the skeletons.
    placeholderData: keepPreviousData,
  });

  // Articles page like reels: 903 competitor articles used to stop at 100.
  const docsQuery = useInfiniteQuery({
    queryKey: ["knowledge-docs", scope, debouncedSearch],
    queryFn: ({ pageParam }) =>
      fetchKnowledgeDocs(debouncedSearch || undefined, scope, pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.next ? allPages.length + 1 : undefined,
    enabled: contentType === "article",
    placeholderData: keepPreviousData,
  });

  const reels = reelsQuery.data?.pages.flatMap((p) => p.results) ?? [];
  const total = reelsQuery.data?.pages[0]?.count ?? 0;
  const docs = docsQuery.data?.pages.flatMap((p) => p.results) ?? [];
  const docsTotal = docsQuery.data?.pages[0]?.count ?? 0;

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="sticky top-0 z-20 space-y-3 border-b border-border bg-white/85 px-4 py-4 backdrop-blur sm:px-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <div>
              <h1 className="text-xl font-bold text-heading">{t("library.title")}</h1>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <ScopeBadge scope={scope} />
                <div className="flex rounded-full border border-border bg-white p-0.5">
                  {(["reel", "article"] as const).map((ct) => (
                    <button
                      key={ct}
                      onClick={() => setContentType(ct)}
                      className={
                        "rounded-full px-3 py-1 text-xs font-bold transition duration-200 " +
                        (contentType === ct
                          ? "bg-secondary/10 text-secondary"
                          : "text-muted hover:text-navy")
                      }
                    >
                      {ct === "reel" ? "Reel" : t("articles.tab")}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <StatBar scope={scope} />
          </div>
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder={t("library.search")}
            className={fieldCls + " w-full"}
          />
          {contentType === "reel" && (
            <FilterBar filters={filters} onChange={setFilters} scope={scope} />
          )}
        </div>

        <div className="flex-1 px-4 py-4 sm:px-6 sm:py-5">
          {contentType === "article" ? (
            docsQuery.isError && !docsQuery.data ? (
              <ErrorState
                onRetry={() => void docsQuery.refetch()}
                retrying={docsQuery.isFetching}
              />
            ) : docsQuery.isLoading ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-44" />
                ))}
              </div>
            ) : docs.length === 0 ? (
              <EmptyState message={t("articles.empty")} />
            ) : (
              <>
                <motion.div
                  variants={staggerContainer}
                  initial="initial"
                  animate="animate"
                  className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-3"
                >
                  {docs.map((doc, i) => (
                    <motion.div key={doc.id} className="h-full" variants={i < 20 ? staggerItem : undefined}>
                      <ArticleCard doc={doc} onClick={() => setOpenDoc(doc.id)} />
                    </motion.div>
                  ))}
                </motion.div>
                <LoadMore
                  shown={docs.length}
                  total={docsTotal}
                  hasMore={!!docsQuery.hasNextPage}
                  loading={docsQuery.isFetchingNextPage}
                  onMore={() => void docsQuery.fetchNextPage()}
                />
              </>
            )
          ) : reelsQuery.isError && !reelsQuery.data ? (
            <ErrorState
              onRetry={() => void reelsQuery.refetch()}
              retrying={reelsQuery.isFetching}
            />
          ) : reelsQuery.isLoading ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
              {Array.from({ length: 10 }).map((_, i) => (
                <Skeleton key={i} className="aspect-[9/16]" />
              ))}
            </div>
          ) : reels.length === 0 ? (
            <EmptyState message={t("library.empty")} />
          ) : (
            <>
              <motion.div
                variants={staggerContainer}
                initial="initial"
                animate="animate"
                className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5"
              >
                {reels.map((reel, i) => (
                  <motion.div key={reel.id} className="h-full" variants={i < 20 ? staggerItem : undefined}>
                    <ReelCard reel={reel} onClick={() => setOpenReel(reel.id)} />
                  </motion.div>
                ))}
              </motion.div>
              <LoadMore
                shown={reels.length}
                total={total}
                hasMore={!!reelsQuery.hasNextPage}
                loading={reelsQuery.isFetchingNextPage}
                onMore={() => void reelsQuery.fetchNextPage()}
              />
            </>
          )}
        </div>

        <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
        <ArticleDetailDrawer docId={openDoc} onClose={() => setOpenDoc(null)} />
      </div>
    </PageTransition>
  );
}

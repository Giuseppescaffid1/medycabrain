import { useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { fetchReels, type ReelFilters, type Scope } from "../api/endpoints";
import { ReelCard } from "../components/reels/ReelCard";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { FilterBar } from "../components/filters/FilterBar";
import { StatBar } from "../components/layout/StatBar";
import { Button, EmptyState, Skeleton, fieldCls } from "../components/ui/primitives";
import { PageTransition, staggerContainer, staggerItem } from "../components/ui/motion";
import { useDebounced } from "../lib/useDebounced";

export default function Library() {
  const { t } = useTranslation();
  const { scope: scopeParam } = useParams();
  const scope: Scope = scopeParam === "medyca" ? "medyca" : "competitor";
  const [filters, setFilters] = useState<ReelFilters>({ ordering: "-posted_at" });
  const [searchInput, setSearchInput] = useState("");
  const [openReel, setOpenReel] = useState<number | null>(null);
  const debouncedSearch = useDebounced(searchInput, 400);

  const effectiveFilters = useMemo(
    () => ({ ...filters, scope, search: debouncedSearch || undefined }),
    [filters, scope, debouncedSearch]
  );

  const { data, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage } =
    useInfiniteQuery({
      queryKey: ["reels", effectiveFilters],
      queryFn: ({ pageParam }) => fetchReels({ ...effectiveFilters, page: pageParam }),
      initialPageParam: 1,
      getNextPageParam: (lastPage, allPages) =>
        lastPage.next ? allPages.length + 1 : undefined,
    });

  const reels = data?.pages.flatMap((p) => p.results) ?? [];
  const total = data?.pages[0]?.count ?? 0;

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="sticky top-0 z-20 space-y-3 border-b border-border bg-white/85 px-4 py-4 backdrop-blur sm:px-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <h1 className="text-xl font-bold text-heading">
              {t(`scope.${scope}`)} · {t("library.title")}
            </h1>
            <StatBar scope={scope} />
          </div>
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder={t("library.search")}
            className={fieldCls + " w-full"}
          />
          <FilterBar filters={filters} onChange={setFilters} scope={scope} />
        </div>

        <div className="flex-1 px-4 py-4 sm:px-6 sm:py-5">
          {isLoading ? (
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
              <div className="mt-6 flex items-center justify-center gap-4">
                <span className="text-xs font-semibold text-muted">
                  {reels.length} / {total}
                </span>
                {hasNextPage && (
                  <Button
                    variant="secondary"
                    onClick={() => fetchNextPage()}
                    loading={isFetchingNextPage}
                  >
                    {t("library.loadMore")}
                  </Button>
                )}
              </div>
            </>
          )}
        </div>

        <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
      </div>
    </PageTransition>
  );
}

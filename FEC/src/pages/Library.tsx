import { useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchReels, type ReelFilters } from "../api/endpoints";
import { ReelCard } from "../components/reels/ReelCard";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { FilterBar } from "../components/filters/FilterBar";
import { StatBar } from "../components/layout/StatBar";
import { Button, EmptyState, Spinner } from "../components/ui/primitives";
import { useDebounced } from "../lib/useDebounced";

export default function Library() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<ReelFilters>({ ordering: "-posted_at" });
  const [searchInput, setSearchInput] = useState("");
  const [openReel, setOpenReel] = useState<number | null>(null);
  const debouncedSearch = useDebounced(searchInput, 400);

  const effectiveFilters = useMemo(
    () => ({ ...filters, search: debouncedSearch || undefined }),
    [filters, debouncedSearch]
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
    <div className="flex h-full flex-col">
      <div className="sticky top-0 z-20 space-y-3 border-b border-zinc-800 bg-zinc-950/95 px-6 py-4 backdrop-blur">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-xl font-bold text-white">{t("library.title")}</h1>
          <StatBar />
        </div>
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder={t("library.search")}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm text-white outline-none focus:border-indigo-500"
        />
        <FilterBar filters={filters} onChange={setFilters} />
      </div>

      <div className="flex-1 px-6 py-5">
        {isLoading ? (
          <Spinner label={t("common.loading")} />
        ) : reels.length === 0 ? (
          <EmptyState message={t("library.empty")} />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
              {reels.map((reel) => (
                <ReelCard key={reel.id} reel={reel} onClick={() => setOpenReel(reel.id)} />
              ))}
            </div>
            <div className="mt-6 flex items-center justify-center gap-4">
              <span className="text-xs text-zinc-500">
                {reels.length} / {total}
              </span>
              {hasNextPage && (
                <Button
                  variant="ghost"
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                >
                  {isFetchingNextPage ? t("common.loading") : t("library.loadMore")}
                </Button>
              )}
            </div>
          </>
        )}
      </div>

      <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
    </div>
  );
}

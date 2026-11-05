import { useState } from "react";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { fetchReels, type Scope } from "../api/endpoints";
import { fetchEngagementOverTime } from "../api/analytics";
import { ReelCard } from "../components/reels/ReelCard";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { EmptyState, ErrorState, Skeleton } from "../components/ui/primitives";
import { LoadMore } from "../components/ui/LoadMore";
import { ScopeBadge } from "../components/ui/ScopeBadge";
import { PageTransition } from "../components/ui/motion";

/** The first/last instant of a YYYY-MM month, as the naive local date-time the
 *  backend reads in its own timezone (the one TruncMonth buckets by). */
function monthBounds(key: string): { posted_after: string; posted_before: string } {
  const [y, m] = key.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  return {
    posted_after: `${key}-01T00:00:00`,
    posted_before: `${key}-${String(last).padStart(2, "0")}T23:59:59`,
  };
}

// Without a month: everything with a date, newest first. The bound also keeps
// out reels with no date, which Postgres would otherwise sort first.
const ALL_DATED = { posted_after: "2000-01-01T00:00:00" };

/** A publication timeline: what was posted, and when. A month histogram you
 *  can click to see the reels of that month.
 *
 *  The histogram comes from the analytics endpoint (one count per month, for
 *  the whole scope); the grid below pages through the reels. The page used to
 *  fetch 400 reels, got the 200 OLDEST (the API caps at 200) and drew the
 *  histogram from them, so the recent months were missing. */
export default function Timeline() {
  const { t } = useTranslation();
  const { scope: scopeParam } = useParams();
  const scope: Scope = scopeParam === "medyca" ? "medyca" : "competitor";
  const [selected, setSelected] = useState<string | null>(null);
  const [openReel, setOpenReel] = useState<number | null>(null);

  // Same key as Analytics: one request serves both pages.
  const monthsQuery = useQuery({
    queryKey: ["an-time", scope],
    queryFn: () => fetchEngagementOverTime(scope),
  });
  const months = monthsQuery.data ?? [];
  const totalPublished = months.reduce((n, m) => n + m.reels, 0);
  const maxCount = Math.max(1, ...months.map((m) => m.reels));

  const grid = useInfiniteQuery({
    queryKey: ["timeline", scope, selected],
    queryFn: ({ pageParam }) =>
      fetchReels({
        scope,
        ordering: "-posted_at",
        page_size: 40,
        page: pageParam,
        ...(selected ? monthBounds(selected) : ALL_DATED),
      }),
    initialPageParam: 1,
    getNextPageParam: (last, all) => (last.next ? all.length + 1 : undefined),
    placeholderData: keepPreviousData,
  });
  const shown = grid.data?.pages.flatMap((p) => p.results) ?? [];
  const shownTotal = grid.data?.pages[0]?.count ?? 0;

  return (
    <PageTransition>
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-4 sm:px-6">
        <h1 className="text-xl font-bold text-heading">{t("timeline.title")}</h1>
        <div className="mt-1 mb-1"><ScopeBadge scope={scope} /></div>
        <p className="text-sm text-muted">{t("timeline.subtitle")}</p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
        {monthsQuery.isError ? (
          <ErrorState
            onRetry={() => void monthsQuery.refetch()}
            retrying={monthsQuery.isFetching}
          />
        ) : monthsQuery.isLoading ? (
          <Skeleton className="h-44" />
        ) : months.length === 0 ? (
          <EmptyState message={t("timeline.empty")} />
        ) : (
          <>
            {/* ── Histogram ────────────────────────────────────────── */}
            <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-muted">
                  {t("timeline.perMonth")}
                </span>
                <span className="text-xs text-muted">
                  {totalPublished} {t("timeline.published")} ·{" "}
                  {fmtMonth(months[0]?.month)} – {fmtMonth(months[months.length - 1]?.month)}
                </span>
              </div>
              <div className="flex items-end gap-1.5 overflow-x-auto pb-1" style={{ minHeight: 140 }}>
                {months.map((m) => {
                  const active = selected === m.month;
                  return (
                    <button
                      key={m.month}
                      onClick={() => setSelected(active ? null : m.month)}
                      className="group flex min-w-[34px] flex-1 flex-col items-center gap-1"
                      title={`${fmtMonth(m.month)}: ${m.reels}`}
                    >
                      <span className={"text-[10px] font-semibold " + (active ? "text-heading" : "text-muted")}>
                        {m.reels}
                      </span>
                      <div
                        className={
                          "w-full rounded-t transition-all " +
                          (active
                            ? "bg-secondary"
                            : "bg-secondary/40 group-hover:bg-secondary/70")
                        }
                        style={{ height: Math.round((m.reels / maxCount) * 96) + 4 }}
                      />
                      <span className={"text-[9px] " + (active ? "text-heading" : "text-muted/80")}>
                        {fmtMonthShort(m.month)}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* ── Selected month / all ─────────────────────────────── */}
            <div className="mt-6">
              <div className="mb-3 flex items-center gap-3">
                <h2 className="text-sm font-bold text-navy">
                  {selected ? fmtMonth(selected) : t("timeline.allRecent")}
                </h2>
                {selected && (
                  <button onClick={() => setSelected(null)} className="text-xs font-semibold text-secondary hover:text-secondary-hover">
                    {t("timeline.showAll")}
                  </button>
                )}
              </div>
              {grid.isError && !grid.data ? (
                <ErrorState
                  compact
                  onRetry={() => void grid.refetch()}
                  retrying={grid.isFetching}
                />
              ) : grid.isLoading ? (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="aspect-[9/16]" />
                  ))}
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
                    {shown.map((reel) => (
                      <ReelCard key={reel.id} reel={reel} onClick={() => setOpenReel(reel.id)} />
                    ))}
                  </div>
                  <LoadMore
                    shown={shown.length}
                    total={shownTotal}
                    hasMore={!!grid.hasNextPage}
                    loading={grid.isFetchingNextPage}
                    onMore={() => void grid.fetchNextPage()}
                  />
                </>
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

function fmtMonth(key?: string): string {
  if (!key) return "";
  const [y, m] = key.split("-");
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString("it-IT", {
    month: "long",
    year: "numeric",
  });
}

function fmtMonthShort(key: string): string {
  const [y, m] = key.split("-");
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString("it-IT", {
    month: "short",
  }) + " '" + y.slice(2);
}

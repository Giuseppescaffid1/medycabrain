import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { fetchReels, type Scope } from "../api/endpoints";
import type { ReelListItem } from "../api/types";
import { ReelCard } from "../components/reels/ReelCard";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { EmptyState, Skeleton } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";

/** A publication timeline: what was posted, and when. A month histogram you
 *  can click to see the reels of that month. */
export default function Timeline() {
  const { t } = useTranslation();
  const { scope: scopeParam } = useParams();
  const scope: Scope = scopeParam === "medyca" ? "medyca" : "competitor";
  const [selected, setSelected] = useState<string | null>(null);
  const [openReel, setOpenReel] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["timeline", scope],
    queryFn: () => fetchReels({ scope, ordering: "posted_at", page_size: 400 }),
  });

  const reels = useMemo(
    () => (data?.results ?? []).filter((r) => r.posted_at),
    [data]
  );

  // Group by month (YYYY-MM), chronological.
  const months = useMemo(() => {
    const map = new Map<string, ReelListItem[]>();
    for (const r of reels) {
      const key = r.posted_at!.slice(0, 7); // YYYY-MM
      (map.get(key) ?? map.set(key, []).get(key)!).push(r);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [reels]);

  const maxCount = Math.max(1, ...months.map(([, rs]) => rs.length));
  const shown = selected
    ? reels.filter((r) => r.posted_at!.slice(0, 7) === selected)
    : reels.slice().reverse(); // newest first when nothing selected

  return (
    <PageTransition>
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-4 sm:px-6">
        <h1 className="text-xl font-bold text-heading">
          {t(`scope.${scope}`)} · {t("timeline.title")}
        </h1>
        <p className="text-sm text-muted">{t("timeline.subtitle")}</p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
        {isLoading ? (
          <Skeleton className="h-44" />
        ) : reels.length === 0 ? (
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
                  {reels.length} {t("timeline.published")} ·{" "}
                  {fmtMonth(months[0]?.[0])} – {fmtMonth(months[months.length - 1]?.[0])}
                </span>
              </div>
              <div className="flex items-end gap-1.5 overflow-x-auto pb-1" style={{ minHeight: 140 }}>
                {months.map(([key, rs]) => {
                  const active = selected === key;
                  return (
                    <button
                      key={key}
                      onClick={() => setSelected(active ? null : key)}
                      className="group flex min-w-[34px] flex-1 flex-col items-center gap-1"
                      title={`${fmtMonth(key)}: ${rs.length}`}
                    >
                      <span className={"text-[10px] font-semibold " + (active ? "text-heading" : "text-muted")}>
                        {rs.length}
                      </span>
                      <div
                        className={
                          "w-full rounded-t transition-all " +
                          (active
                            ? "bg-secondary"
                            : "bg-secondary/40 group-hover:bg-secondary/70")
                        }
                        style={{ height: Math.round((rs.length / maxCount) * 96) + 4 }}
                      />
                      <span className={"text-[9px] " + (active ? "text-heading" : "text-muted/80")}>
                        {fmtMonthShort(key)}
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
                <span className="text-xs text-muted/80">{shown.length}</span>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
                {shown.map((reel) => (
                  <ReelCard key={reel.id} reel={reel} onClick={() => setOpenReel(reel.id)} />
                ))}
              </div>
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

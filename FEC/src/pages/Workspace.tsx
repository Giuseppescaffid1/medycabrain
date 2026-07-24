import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchReels, fetchTags, type ReelFilters } from "../api/endpoints";
import { ReelCard } from "../components/reels/ReelCard";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { EmptyState, Skeleton } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";

type TabKey = "favorites" | "inspiration" | "tags";

export default function Workspace() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>("favorites");
  const [tagId, setTagId] = useState<number | undefined>();
  const [openReel, setOpenReel] = useState<number | null>(null);

  const { data: tags } = useQuery({ queryKey: ["tags"], queryFn: fetchTags });

  const filters: ReelFilters =
    tab === "favorites"
      ? { favorite: true, page_size: 60 }
      : tab === "inspiration"
        ? { inspiration: true, page_size: 60 }
        : { tag: tagId, page_size: 60 };

  const { data, isLoading } = useQuery({
    queryKey: ["workspace", tab, tagId],
    queryFn: () => fetchReels(filters),
    enabled: tab !== "tags" || tagId != null,
  });

  const tabs: { key: TabKey; label: string }[] = [
    { key: "favorites", label: t("workspace.favorites") },
    { key: "inspiration", label: t("workspace.inspiration") },
    { key: "tags", label: t("workspace.tags") },
  ];

  return (
    <PageTransition>
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-4 sm:px-6">
        <h1 className="mb-3 text-xl font-bold text-heading">{t("workspace.title")}</h1>
        <div className="flex flex-wrap gap-2">
          {tabs.map((tb) => (
            <button
              key={tb.key}
              onClick={() => setTab(tb.key)}
              className={
                "rounded-full border px-4 py-1.5 text-sm font-semibold transition " +
                (tab === tb.key
                  ? "border-secondary bg-surface text-heading"
                  : "border-border bg-white text-muted hover:text-navy")
              }
            >
              {tb.label}
            </button>
          ))}
        </div>
        {tab === "tags" && (
          <div className="mt-3 flex flex-wrap gap-2">
            {tags?.length ? (
              tags.map((tg) => (
                <button
                  key={tg.id}
                  onClick={() => setTagId(tg.id)}
                  className={
                    "rounded-full px-3 py-1 text-xs font-medium transition " +
                    (tagId === tg.id ? "ring-2 ring-secondary" : "")
                  }
                  style={{ backgroundColor: tg.color + "22", color: tg.color }}
                >
                  {tg.name}
                </button>
              ))
            ) : (
              <span className="text-xs text-muted/80">—</span>
            )}
          </div>
        )}
      </div>

      <div className="flex-1 px-4 py-4 sm:px-6 sm:py-5">
        {isLoading ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="aspect-[9/16]" />
            ))}
          </div>
        ) : !data || data.results.length === 0 ? (
          <EmptyState message={t("workspace.empty")} />
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
            {data.results.map((reel) => (
              <ReelCard key={reel.id} reel={reel} onClick={() => setOpenReel(reel.id)} />
            ))}
          </div>
        )}
      </div>

      <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
    </div>
    </PageTransition>
  );
}

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchReels, fetchTags, type ReelFilters } from "../api/endpoints";
import { ReelCard } from "../components/reels/ReelCard";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { EmptyState, Spinner } from "../components/ui/primitives";

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
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 py-4">
        <h1 className="mb-3 text-xl font-bold text-white">{t("workspace.title")}</h1>
        <div className="flex flex-wrap gap-2">
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
        {tab === "tags" && (
          <div className="mt-3 flex flex-wrap gap-2">
            {tags?.length ? (
              tags.map((tg) => (
                <button
                  key={tg.id}
                  onClick={() => setTagId(tg.id)}
                  className={
                    "rounded-full px-3 py-1 text-xs font-medium transition " +
                    (tagId === tg.id ? "ring-2 ring-indigo-400" : "")
                  }
                  style={{ backgroundColor: tg.color + "22", color: tg.color }}
                >
                  {tg.name}
                </button>
              ))
            ) : (
              <span className="text-xs text-zinc-600">—</span>
            )}
          </div>
        )}
      </div>

      <div className="flex-1 px-6 py-5">
        {isLoading ? (
          <Spinner />
        ) : !data || data.results.length === 0 ? (
          <EmptyState message={t("workspace.empty")} />
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
            {data.results.map((reel) => (
              <ReelCard key={reel.id} reel={reel} onClick={() => setOpenReel(reel.id)} />
            ))}
          </div>
        )}
      </div>

      <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
    </div>
  );
}

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  fetchCluster,
  fetchClusterArguments,
  fetchReels,
} from "../api/endpoints";
import { ReelCard } from "../components/reels/ReelCard";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { Badge, Spinner } from "../components/ui/primitives";

export default function ClusterDetail() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id, scope: scopeParam } = useParams();
  const scope = scopeParam === "medyca" ? "medyca" : "competitor";
  const clusterId = Number(id);
  const [openReel, setOpenReel] = useState<number | null>(null);

  const { data: cluster } = useQuery({
    queryKey: ["cluster", clusterId],
    queryFn: () => fetchCluster(clusterId),
  });
  const { data: args } = useQuery({
    queryKey: ["cluster-args", clusterId],
    queryFn: () => fetchClusterArguments(clusterId),
  });
  const { data: reels, isLoading } = useQuery({
    queryKey: ["cluster-reels", clusterId],
    queryFn: () => fetchReels({ cluster: clusterId, page_size: 60 }),
  });

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 py-4">
        <button
          onClick={() => navigate(`/${scope}/clusters`)}
          className="mb-2 text-xs text-zinc-500 hover:text-zinc-300"
        >
          ← {t("clusters.backToClusters")}
        </button>
        <h1 className="text-xl font-bold text-white">{cluster?.label_it ?? "…"}</h1>
        {cluster?.description_it && (
          <p className="mt-1 text-sm text-zinc-400">{cluster.description_it}</p>
        )}
      </div>

      <div className="flex-1 space-y-6 px-6 py-5">
        {args && args.length > 0 && (
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
              {t("clusters.arguments")}
            </h2>
            <ul className="space-y-2">
              {args.map((a, i) => (
                <li
                  key={i}
                  className="flex items-start justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-2.5"
                >
                  <span className="text-sm text-zinc-200">{a.text}</span>
                  <Badge className="shrink-0 bg-indigo-600/20 text-indigo-300">
                    {t("clusters.saidInNReels", { count: a.reel_count })}
                  </Badge>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            {t("clusters.reels")}
          </h2>
          {isLoading ? (
            <Spinner />
          ) : (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
              {reels?.results.map((reel) => (
                <ReelCard key={reel.id} reel={reel} onClick={() => setOpenReel(reel.id)} />
              ))}
            </div>
          )}
        </section>
      </div>

      <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { fetchClusters } from "../api/endpoints";
import type { Cluster } from "../api/types";
import { Badge, EmptyState, Spinner } from "../components/ui/primitives";
import { mediaUrl } from "../lib/utils";

export default function Clusters() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["clusters"], queryFn: fetchClusters });

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-xl font-bold text-white">{t("clusters.title")}</h1>
        <p className="text-sm text-zinc-500">{t("clusters.subtitle")}</p>
      </div>
      <div className="flex-1 px-6 py-5">
        {isLoading ? (
          <Spinner />
        ) : !data || data.length === 0 ? (
          <EmptyState message={t("clusters.empty")} />
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.map((c) => (
              <ClusterCard key={c.id} cluster={c} onClick={() => navigate(`/clusters/${c.id}`)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ClusterCard({ cluster, onClick }: { cluster: Cluster; onClick: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      onClick={onClick}
      className="flex flex-col gap-3 rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-left transition hover:border-indigo-600/60"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-base font-semibold text-white">{cluster.label_it}</h3>
        <Badge className="shrink-0 bg-indigo-600/20 text-indigo-300">
          {cluster.size} {t("clusters.reels")}
        </Badge>
      </div>
      {cluster.description_it && (
        <p className="line-clamp-2 text-sm text-zinc-400">{cluster.description_it}</p>
      )}
      {cluster.keywords?.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {cluster.keywords.map((k) => (
            <Badge key={k}>{k}</Badge>
          ))}
        </div>
      )}
      {cluster.preview_thumbs?.length > 0 && (
        <div className="mt-auto flex gap-2">
          {cluster.preview_thumbs.map((thmb, i) => (
            <div key={i} className="aspect-[9/16] w-14 overflow-hidden rounded bg-zinc-800">
              <img src={mediaUrl(thmb) ?? ""} alt="" className="h-full w-full object-cover" />
            </div>
          ))}
        </div>
      )}
    </button>
  );
}

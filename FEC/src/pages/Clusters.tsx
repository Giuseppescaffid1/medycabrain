import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { fetchClusters, type Scope } from "../api/endpoints";
import type { Cluster } from "../api/types";
import { motion } from "framer-motion";
import { Badge, EmptyState, Skeleton } from "../components/ui/primitives";
import { PageTransition, staggerContainer, staggerItem } from "../components/ui/motion";
import { mediaUrl } from "../lib/utils";

export default function Clusters() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { scope: scopeParam } = useParams();
  const scope: Scope = scopeParam === "medyca" ? "medyca" : "competitor";
  const { data, isLoading } = useQuery({
    queryKey: ["clusters", scope],
    queryFn: () => fetchClusters(scope),
  });

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-4 py-4 sm:px-6">
          <h1 className="text-xl font-bold text-heading">{t(`scope.${scope}`)} · {t("clusters.title")}</h1>
          <p className="text-sm text-muted">{t("clusters.subtitle")}</p>
        </div>
        <div className="flex-1 px-4 py-4 sm:px-6 sm:py-5">
          {isLoading ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-48" />
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <EmptyState message={t("clusters.empty")} />
          ) : (
            <motion.div
              variants={staggerContainer}
              initial="initial"
              animate="animate"
              className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
            >
              {data.map((c) => (
                <motion.div key={c.id} className="h-full" variants={staggerItem}>
                  <ClusterCard cluster={c} onClick={() => navigate(`/${scope}/clusters/${c.id}`)} />
                </motion.div>
              ))}
            </motion.div>
          )}
        </div>
      </div>
    </PageTransition>
  );
}

function ClusterCard({ cluster, onClick }: { cluster: Cluster; onClick: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      onClick={onClick}
      className="flex h-full w-full flex-col gap-3 rounded-xl border border-border bg-surface p-4 text-left shadow-card transition duration-200 hover:-translate-y-0.5 hover:border-secondary hover:shadow-float"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-base font-bold text-heading">{cluster.label_it}</h3>
        <Badge className="shrink-0 bg-white text-heading">
          {cluster.size} {t("clusters.reels")}
        </Badge>
      </div>
      {cluster.description_it && (
        <p className="line-clamp-2 text-sm text-muted">{cluster.description_it}</p>
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
            <div key={i} className="aspect-[9/16] w-14 overflow-hidden rounded-md bg-white">
              <img src={mediaUrl(thmb) ?? ""} alt="" className="h-full w-full object-cover" />
            </div>
          ))}
        </div>
      )}
    </button>
  );
}

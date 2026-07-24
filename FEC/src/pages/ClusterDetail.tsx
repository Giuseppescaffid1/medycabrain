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
import { Badge, Button, Skeleton } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";
import { useJobs } from "../contexts/JobsContext";

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
    <PageTransition>
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-4 sm:px-6">
        <button
          onClick={() => navigate(`/${scope}/clusters`)}
          className="mb-2 text-xs font-semibold text-muted hover:text-navy"
        >
          ← {t("clusters.backToClusters")}
        </button>
        <h1 className="text-xl font-bold text-heading">{cluster?.label_it ?? "…"}</h1>
        {cluster?.description_it && (
          <p className="mt-1 text-sm text-muted">{cluster.description_it}</p>
        )}
        {cluster && <BlogPanel cluster={cluster} />}
      </div>

      <div className="flex-1 space-y-6 px-4 py-4 sm:px-6 sm:py-5">
        {args && args.length > 0 && (
          <section>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
              {t("clusters.arguments")}
            </h2>
            <ul className="space-y-2">
              {args.map((a, i) => (
                <li
                  key={i}
                  className="flex items-start justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-2.5 shadow-card"
                >
                  <span className="text-sm text-navy">{a.text}</span>
                  <Badge className="shrink-0 bg-white text-heading">
                    {t("clusters.saidInNReels", { count: a.reel_count })}
                  </Badge>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
            {t("clusters.reels")}
          </h2>
          {isLoading ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="aspect-[9/16]" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
              {reels?.results.map((reel) => (
                <ReelCard key={reel.id} reel={reel} onClick={() => setOpenReel(reel.id)} />
              ))}
            </div>
          )}
        </section>
      </div>

      <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
    </div>
    </PageTransition>
  );
}

function BlogPanel({ cluster }: { cluster: import("../api/types").Cluster }) {
  const { t } = useTranslation();
  const { jobs, startClusterBlog } = useJobs();
  const running = jobs.some((j) => j.kind === "blog" && (j.status === "queued" || j.status === "running"));

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-2.5 shadow-card">
      <span className="text-xs font-semibold text-muted">
        {cluster.reel_count} reel · {cluster.doc_count} {t("blog.articles")}
      </span>
      {cluster.has_blog ? (
        <Badge className="bg-success/10 text-success">{t("blog.hasArticle")}</Badge>
      ) : (
        <Badge className="bg-warning/10 text-warning">{t("blog.noArticle")}</Badge>
      )}
      <Button
        variant="secondary"
        onClick={() => startClusterBlog(cluster.id)}
        disabled={running}
      >
        {running
          ? t("blog.generating")
          : cluster.has_blog
            ? `✍️ ${t("blog.expand")}`
            : `✍️ ${t("blog.draft")}`}
      </Button>
      <span className="text-xs text-muted/80">{t("blog.resultInSecondBrain")}</span>
    </div>
  );
}

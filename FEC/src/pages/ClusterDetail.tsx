import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  fetchCluster,
  fetchClusterArguments,
  fetchReels,
  type Scope,
} from "../api/endpoints";
import { errorStatus } from "../api/client";
import { fetchClusterDocs } from "../api/knowledge";
import { ReelCard } from "../components/reels/ReelCard";
import { ArticleCard } from "../components/articles/ArticleCard";
import { ArticleDetailDrawer } from "../components/articles/ArticleDetailDrawer";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { Badge, Button, ErrorState, Skeleton } from "../components/ui/primitives";
import { LoadMore } from "../components/ui/LoadMore";
import { ScopeBadge } from "../components/ui/ScopeBadge";
import { PageTransition } from "../components/ui/motion";
import { useJobs } from "../contexts/JobsContext";

export default function ClusterDetail() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id, scope: scopeParam } = useParams();
  const scope: Scope = scopeParam === "medyca" ? "medyca" : "competitor";
  const clusterId = Number(id);
  const [openReel, setOpenReel] = useState<number | null>(null);
  const [openDoc, setOpenDoc] = useState<number | null>(null);

  const clusterQuery = useQuery({
    queryKey: ["cluster", clusterId],
    queryFn: () => fetchCluster(clusterId),
  });
  const cluster = clusterQuery.data;

  // The cluster endpoint answers any id, so a link pasted under the wrong side
  // (/medyca/clusters/<competitor id>) would show competitor content under
  // Medyca's name: the one mix-up this product must never make. The cluster
  // says which side it belongs to; the rest of the page loads only once the
  // URL agrees with it.
  const sameSide = !!cluster && cluster.scope === scope;

  const argsQuery = useQuery({
    queryKey: ["cluster-args", clusterId],
    queryFn: () => fetchClusterArguments(clusterId),
    enabled: sameSide,
  });
  const args = argsQuery.data;

  const docsQuery = useInfiniteQuery({
    queryKey: ["cluster-docs", clusterId],
    queryFn: ({ pageParam }) => fetchClusterDocs(clusterId, pageParam),
    initialPageParam: 1,
    getNextPageParam: (last, all) => (last.next ? all.length + 1 : undefined),
    enabled: sameSide,
  });
  const docs = docsQuery.data?.pages.flatMap((p) => p.results) ?? [];

  // Up to 146 reels in the biggest cluster: the page used to stop at 60.
  const reelsQuery = useInfiniteQuery({
    queryKey: ["cluster-reels", clusterId],
    queryFn: ({ pageParam }) => fetchReels({ cluster: clusterId, page_size: 48, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (last, all) => (last.next ? all.length + 1 : undefined),
    enabled: sameSide,
  });
  const reels = reelsQuery.data?.pages.flatMap((p) => p.results) ?? [];

  if (cluster && !sameSide) {
    return <Navigate to={`/${cluster.scope}/clusters/${cluster.id}`} replace />;
  }

  const back = (
    <Button variant="secondary" onClick={() => navigate(`/${scope}/clusters`)}>
      {t("clusters.backToClusters")}
    </Button>
  );

  if (clusterQuery.isError) {
    const gone = errorStatus(clusterQuery.error) === 404;
    return (
      <PageTransition>
        <ErrorState
          message={gone ? t("clusters.notFound") : undefined}
          onRetry={gone ? undefined : () => void clusterQuery.refetch()}
          retrying={clusterQuery.isFetching}
        >
          {back}
        </ErrorState>
      </PageTransition>
    );
  }

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
        <div className="mt-1 mb-1"><ScopeBadge scope={scope} /></div>
        {cluster?.description_it && (
          <p className="mt-1 text-sm text-muted">{cluster.description_it}</p>
        )}
        {cluster && <BlogPanel cluster={cluster} />}
      </div>

      <div className="flex-1 space-y-6 px-4 py-4 sm:px-6 sm:py-5">
        {argsQuery.isError && (
          <ErrorState
            compact
            onRetry={() => void argsQuery.refetch()}
            retrying={argsQuery.isFetching}
          />
        )}
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
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    {a.reel_count > 0 && (
                      <Badge className="bg-white text-heading">
                        {t("clusters.saidInNReels", { count: a.reel_count })}
                      </Badge>
                    )}
                    {(a.article_count ?? 0) > 0 && (
                      <Badge className="bg-white text-heading">
                        📄 {t("clusters.inNArticles", { count: a.article_count })}
                      </Badge>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {docsQuery.isError && (
          <ErrorState
            compact
            onRetry={() => void docsQuery.refetch()}
            retrying={docsQuery.isFetching}
          />
        )}
        {docs.length > 0 && (
          <section>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
              {t("articles.tab")} · {docsQuery.data?.pages[0]?.count ?? docs.length}
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-3">
              {docs.map((d) => (
                <ArticleCard key={d.id} doc={d} onClick={() => setOpenDoc(d.id)} />
              ))}
            </div>
            {docsQuery.hasNextPage && (
              <LoadMore
                shown={docs.length}
                total={docsQuery.data?.pages[0]?.count ?? docs.length}
                hasMore
                loading={docsQuery.isFetchingNextPage}
                onMore={() => void docsQuery.fetchNextPage()}
              />
            )}
          </section>
        )}

        <section>
          <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">
            {t("clusters.reels")}
          </h2>
          {reelsQuery.isError ? (
            <ErrorState
              compact
              onRetry={() => void reelsQuery.refetch()}
              retrying={reelsQuery.isFetching}
            />
          ) : !sameSide || reelsQuery.isLoading ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="aspect-[9/16]" />
              ))}
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 xl:grid-cols-5">
                {reels.map((reel) => (
                  <ReelCard key={reel.id} reel={reel} onClick={() => setOpenReel(reel.id)} />
                ))}
              </div>
              <LoadMore
                shown={reels.length}
                total={reelsQuery.data?.pages[0]?.count ?? reels.length}
                hasMore={!!reelsQuery.hasNextPage}
                loading={reelsQuery.isFetchingNextPage}
                onMore={() => void reelsQuery.fetchNextPage()}
              />
            </>
          )}
        </section>
      </div>

      <ReelDetailDrawer reelId={openReel} onClose={() => setOpenReel(null)} />
      <ArticleDetailDrawer docId={openDoc} onClose={() => setOpenDoc(null)} />
    </div>
    </PageTransition>
  );
}

function BlogPanel({ cluster }: { cluster: import("../api/types").Cluster }) {
  const { t } = useTranslation();
  const { jobs, startClusterBlog, starting } = useJobs();
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
        disabled={running || starting}
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

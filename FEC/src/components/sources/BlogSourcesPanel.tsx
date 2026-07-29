import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  addBlogSource,
  crawlBlogSource,
  deleteBlogSource,
  fetchBlogSources,
  reactivateBlogSource,
  updateBlogSource,
} from "../../api/blogSources";
import { Badge, Button, Skeleton, fieldCls } from "../ui/primitives";
import { formatDate } from "../../lib/utils";

/**
 * The blogs we track, next to the Instagram accounts.
 *
 * The promise of this panel is "paste a URL and the agent does the rest":
 * adding a source queues discovery immediately, so articles appear within
 * minutes, not after the nightly run. A source that failed repeatedly shows
 * WHY and can be brought back deliberately — deactivation is automatic,
 * reactivation is a human act.
 */
export function BlogSourcesPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [owner, setOwner] = useState<"owned" | "competitor">("competitor");
  const [error, setError] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["blog-sources"],
    queryFn: fetchBlogSources,
    // Crawls run in the background: keep the row counts moving while the
    // user watches the source they just added fill up.
    refetchInterval: 15000,
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["blog-sources"] });

  const add = useMutation({
    mutationFn: addBlogSource,
    onSuccess: () => {
      setName("");
      setUrl("");
      setError("");
      invalidate();
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: Record<string, string[]> } })
        ?.response?.data;
      const first = detail && Object.values(detail)[0];
      setError(Array.isArray(first) ? first[0] : t("common.error"));
    },
  });
  const toggle = useMutation({
    mutationFn: (v: { id: number; is_active: boolean }) =>
      updateBlogSource(v.id, { is_active: v.is_active }),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: deleteBlogSource, onSuccess: invalidate });
  const crawl = useMutation({ mutationFn: crawlBlogSource, onSuccess: invalidate });
  const reactivate = useMutation({ mutationFn: reactivateBlogSource, onSuccess: invalidate });

  return (
    <section>
      <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
        {t("sources.title")}
      </h2>
      <p className="mb-4 text-sm text-muted">{t("sources.subtitle")}</p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          const u = url.trim();
          if (!u) return;
          add.mutate({
            name: name.trim() || new URL(u.startsWith("http") ? u : `https://${u}`).hostname.replace(/^www\./, ""),
            index_url: u.startsWith("http") ? u : `https://${u}`,
            owner_type: owner,
          });
        }}
        className="mb-2 flex max-w-3xl flex-wrap gap-2"
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("sources.namePlaceholder")}
          className={fieldCls + " w-44 min-w-0"}
        />
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t("sources.urlPlaceholder")}
          className={fieldCls + " min-w-0 flex-1"}
        />
        <select
          value={owner}
          onChange={(e) => setOwner(e.target.value as "owned" | "competitor")}
          className={fieldCls + " w-36"}
          aria-label={t("sources.ownerLabel")}
        >
          <option value="competitor">{t("scope.competitor")}</option>
          <option value="owned">{t("scope.medyca")}</option>
        </select>
        <Button type="submit" loading={add.isPending}>
          {t("sources.add")}
        </Button>
      </form>
      <p className="mb-4 text-xs text-muted/80">{t("sources.addHint")}</p>
      {error && <p className="mb-4 text-sm font-semibold text-danger">⚠ {error}</p>}

      {isLoading ? (
        <Skeleton className="h-40" />
      ) : !data?.length ? (
        <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted shadow-card">
          {t("sources.empty")}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-surface text-left text-xs font-bold uppercase tracking-wider text-muted">
              <tr>
                <th className="px-4 py-3">{t("sources.source")}</th>
                <th className="px-4 py-3">{t("sources.owner")}</th>
                <th className="px-4 py-3 text-right">{t("sources.articles")}</th>
                <th className="px-4 py-3">{t("sources.lastCrawl")}</th>
                <th className="px-4 py-3">{t("accounts.status")}</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.map((s) => {
                const comp = s.owner_type === "competitor";
                const failedOut = !s.is_active && s.consecutive_failures > 0;
                return (
                  <tr key={s.id} className="text-navy">
                    <td className="px-4 py-3">
                      <div className="font-semibold">{s.name}</div>
                      <a
                        href={s.index_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-muted hover:text-secondary"
                      >
                        {s.index_url.replace(/^https?:\/\/(www\.)?/, "")}
                      </a>
                      {s.last_error && (
                        <div className="mt-1 max-w-xs truncate text-xs text-danger"
                             title={s.last_error}>
                          ⚠ {s.last_error}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge className={comp ? "bg-warning/10 text-warning" : "bg-secondary/10 text-secondary"}>
                        {comp ? t("scope.competitor") : t("scope.medyca")}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{s.document_count ?? 0}</td>
                    <td className="px-4 py-3 text-xs text-muted">
                      {s.last_crawled_at ? formatDate(s.last_crawled_at) : t("accounts.never")}
                    </td>
                    <td className="px-4 py-3">
                      {failedOut ? (
                        <button
                          onClick={() => reactivate.mutate(s.id)}
                          title={t("sources.reactivateHint")}
                        >
                          <Badge className="bg-danger/10 text-danger">{t("sources.failed")}</Badge>
                        </button>
                      ) : (
                        <button onClick={() => toggle.mutate({ id: s.id, is_active: !s.is_active })}>
                          <Badge className={s.is_active ? "bg-success/10 text-success" : "bg-surface text-muted"}>
                            {s.is_active ? t("accounts.active") : t("accounts.inactive")}
                          </Badge>
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <button
                          onClick={() => crawl.mutate(s.id)}
                          disabled={crawl.isPending || !s.is_active}
                          className="text-xs font-semibold text-secondary hover:text-heading disabled:opacity-50"
                        >
                          {t("sources.crawlNow")}
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(t("sources.confirmRemove"))) remove.mutate(s.id);
                          }}
                          className="text-xs font-semibold text-muted hover:text-danger"
                        >
                          {t("accounts.remove")}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

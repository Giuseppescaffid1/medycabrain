import { useMemo, useState } from "react";
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
import {
  AddForm,
  FilterSelect,
  FormError,
  PanelEmpty,
  PanelHeader,
  ResultCount,
  RowAction,
  RowActions,
  SearchField,
  StatusToggle,
  TableFrame,
  Th,
  Toolbar,
} from "../manage/parts";
import { formatDate } from "../../lib/utils";

/**
 * The blogs we track, next to the Instagram accounts.
 *
 * The promise of this panel is "paste a URL and the agent does the rest":
 * adding a source queues discovery immediately, so articles appear within
 * minutes, not after the nightly run. A source that failed repeatedly shows
 * WHY and can be brought back deliberately — deactivation is automatic,
 * reactivation is a human act.
 *
 * Layout follows the shared shape in `manage/parts`: list first, add form
 * only when asked for, search and status filter above the table.
 */
export function BlogSourcesPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [owner, setOwner] = useState<"owned" | "competitor">("competitor");
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");

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
      setAdding(false);
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

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter((s) => {
      const failedOut = !s.is_active && s.consecutive_failures > 0;
      if (status === "active" && !s.is_active) return false;
      if (status === "inactive" && (s.is_active || failedOut)) return false;
      if (status === "failed" && !failedOut) return false;
      if (status === "owned" && s.owner_type !== "owned") return false;
      if (status === "competitor" && s.owner_type !== "competitor") return false;
      if (!needle) return true;
      return (
        s.name.toLowerCase().includes(needle) || s.index_url.toLowerCase().includes(needle)
      );
    });
  }, [data, q, status]);

  const addButton = (
    <Button
      variant={adding ? "secondary" : "primary"}
      onClick={() => {
        setAdding((v) => !v);
        setError("");
      }}
    >
      {adding ? t("manage.cancel") : t("sources.add")}
    </Button>
  );

  return (
    <section aria-labelledby="tab-blogs" id="panel-blogs" role="tabpanel">
      <PanelHeader description={t("sources.subtitle")} action={addButton} />

      <AddForm open={adding}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const u = url.trim();
            if (!u) {
              setError(t("sources.urlRequired"));
              return;
            }
            const full = u.startsWith("http") ? u : `https://${u}`;
            let host = "";
            try {
              host = new URL(full).hostname.replace(/^www\./, "");
            } catch {
              setError(t("sources.urlInvalid"));
              return;
            }
            add.mutate({
              name: name.trim() || host,
              index_url: full,
              owner_type: owner,
            });
          }}
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
        >
          <label className="flex flex-col gap-1 sm:w-44">
            <span className="text-xs font-bold uppercase tracking-wider text-muted">
              {t("sources.nameLabel")}
            </span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("sources.namePlaceholder")}
              className={fieldCls + " min-w-0"}
            />
          </label>
          <label className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="text-xs font-bold uppercase tracking-wider text-muted">
              {t("sources.urlLabel")}
            </span>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t("sources.urlPlaceholder")}
              className={fieldCls + " min-w-0"}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-bold uppercase tracking-wider text-muted">
              {t("sources.ownerLabel")}
            </span>
            <select
              value={owner}
              onChange={(e) => setOwner(e.target.value as "owned" | "competitor")}
              className={fieldCls + " w-full sm:w-44"}
            >
              <option value="competitor">{t("scope.competitor")}</option>
              <option value="owned">{t("scope.medyca")}</option>
            </select>
          </label>
          <Button type="submit" loading={add.isPending}>
            {t("sources.add")}
          </Button>
        </form>
        <p className="mt-3 text-xs text-muted/80">{t("sources.addHint")}</p>
        {error && <FormError message={error} />}
      </AddForm>

      {isLoading ? (
        <Skeleton className="h-40" />
      ) : !data?.length ? (
        <PanelEmpty message={t("sources.empty")} />
      ) : (
        <>
          <Toolbar>
            <SearchField value={q} onChange={setQ} placeholder={t("manage.searchBlogs")} />
            <FilterSelect
              value={status}
              onChange={setStatus}
              label={t("manage.filterLabel")}
              options={[
                { value: "all", label: t("manage.filterAll") },
                { value: "active", label: t("accounts.active") },
                { value: "inactive", label: t("accounts.inactive") },
                { value: "failed", label: t("sources.failed") },
                { value: "owned", label: t("scope.medyca") },
                { value: "competitor", label: t("scope.competitor") },
              ]}
            />
            <ResultCount shown={rows.length} total={data.length} />
          </Toolbar>

          {!rows.length ? (
            <PanelEmpty message={t("manage.noResults")} />
          ) : (
            <TableFrame
              minWidth={760}
              head={
                <>
                  <Th>{t("sources.source")}</Th>
                  <Th>{t("sources.owner")}</Th>
                  <Th align="right">{t("sources.articles")}</Th>
                  <Th>{t("sources.lastCrawl")}</Th>
                  <Th>{t("accounts.status")}</Th>
                  <Th align="right" />
                </>
              }
            >
              {rows.map((s) => {
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
                        <div
                          className="mt-1 max-w-xs truncate text-xs text-danger"
                          title={s.last_error}
                        >
                          ⚠ {s.last_error}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        className={
                          comp ? "bg-warning/10 text-warning" : "bg-secondary/10 text-secondary"
                        }
                      >
                        {comp ? t("scope.competitor") : t("scope.medyca")}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{s.document_count ?? 0}</td>
                    <td className="px-4 py-3 text-xs text-muted">
                      {s.last_crawled_at ? formatDate(s.last_crawled_at) : t("accounts.never")}
                    </td>
                    <td className="px-4 py-3">
                      {failedOut ? (
                        <StatusToggle
                          onClick={() => reactivate.mutate(s.id)}
                          title={t("sources.reactivateHint")}
                        >
                          <Badge className="bg-danger/10 text-danger">{t("sources.failed")}</Badge>
                        </StatusToggle>
                      ) : (
                        <StatusToggle
                          onClick={() => toggle.mutate({ id: s.id, is_active: !s.is_active })}
                          title={t("manage.toggleHint")}
                        >
                          <Badge
                            className={
                              s.is_active ? "bg-success/10 text-success" : "bg-surface text-muted"
                            }
                          >
                            {s.is_active ? t("accounts.active") : t("accounts.inactive")}
                          </Badge>
                        </StatusToggle>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <RowActions>
                        <RowAction
                          tone="action"
                          onClick={() => crawl.mutate(s.id)}
                          disabled={crawl.isPending || !s.is_active}
                        >
                          {t("sources.crawlNow")}
                        </RowAction>
                        <RowAction
                          tone="danger"
                          onClick={() => {
                            if (confirm(t("sources.confirmRemove"))) remove.mutate(s.id);
                          }}
                        >
                          {t("accounts.remove")}
                        </RowAction>
                      </RowActions>
                    </td>
                  </tr>
                );
              })}
            </TableFrame>
          )}
        </>
      )}
    </section>
  );
}

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  addAccount,
  deleteAccount,
  fetchAccounts,
  updateAccount,
} from "../../api/endpoints";
import type { Account } from "../../api/types";
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
import { formatCount, formatDate } from "../../lib/utils";

/**
 * The Instagram profiles we collect reels from.
 *
 * Lifted out of the page so the three managed things (profiles, blogs,
 * uploads) share one panel shape. Owner type is set when adding, because
 * mixing Medyca's own content with a competitor's is the one mistake this
 * platform must never make.
 */
export function AccountsPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [username, setUsername] = useState("");
  const [owner, setOwner] = useState<Account["owner_type"]>("competitor");
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");

  const { data, isLoading } = useQuery({ queryKey: ["accounts"], queryFn: fetchAccounts });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["accounts"] });

  const add = useMutation({
    mutationFn: (v: { username: string; owner: Account["owner_type"] }) =>
      addAccount(v.username, v.owner),
    onSuccess: () => {
      setUsername("");
      setError("");
      setAdding(false);
      invalidate();
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: Record<string, string[]> } })?.response?.data;
      const first = detail && Object.values(detail)[0];
      setError(Array.isArray(first) ? first[0] : t("common.error"));
    },
  });
  const toggle = useMutation({
    mutationFn: (v: { id: number; is_active: boolean }) =>
      updateAccount(v.id, { is_active: v.is_active }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteAccount(id),
    onSuccess: invalidate,
  });

  const clean = (u: string) => u.trim().replace(/^@/, "").replace(/\/$/, "");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter((a) => {
      if (status === "active" && !a.is_active) return false;
      if (status === "inactive" && a.is_active) return false;
      if (status === "owned" && a.owner_type !== "owned") return false;
      if (status === "competitor" && a.owner_type !== "competitor") return false;
      if (!needle) return true;
      return (
        a.username.toLowerCase().includes(needle) ||
        (a.display_name ?? "").toLowerCase().includes(needle)
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
      {adding ? t("manage.cancel") : t("accounts.add")}
    </Button>
  );

  return (
    <section aria-labelledby="tab-instagram" id="panel-instagram" role="tabpanel">
      <PanelHeader description={t("accounts.igSubtitle")} action={addButton} />

      <AddForm open={adding}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const u = clean(username);
            if (!u) {
              setError(t("accounts.usernameRequired"));
              return;
            }
            add.mutate({ username: u, owner });
          }}
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
        >
          <label className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="text-xs font-bold uppercase tracking-wider text-muted">
              {t("accounts.username")}
            </span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t("accounts.addPlaceholder")}
              className={fieldCls + " min-w-0"}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-bold uppercase tracking-wider text-muted">
              {t("accounts.ownerLabel")}
            </span>
            <select
              value={owner}
              onChange={(e) => setOwner(e.target.value as Account["owner_type"])}
              className={fieldCls + " w-full sm:w-44"}
            >
              <option value="competitor">{t("scope.competitor")}</option>
              <option value="owned">{t("scope.medyca")}</option>
            </select>
          </label>
          <Button type="submit" loading={add.isPending}>
            {t("accounts.add")}
          </Button>
        </form>
        {error && <FormError message={error} />}
      </AddForm>

      {isLoading ? (
        <Skeleton className="h-64" />
      ) : !data?.length ? (
        <PanelEmpty message={t("accounts.empty")} />
      ) : (
        <>
          <Toolbar>
            <SearchField value={q} onChange={setQ} placeholder={t("manage.searchAccounts")} />
            <FilterSelect
              value={status}
              onChange={setStatus}
              label={t("manage.filterLabel")}
              options={[
                { value: "all", label: t("manage.filterAll") },
                { value: "active", label: t("accounts.active") },
                { value: "inactive", label: t("accounts.inactive") },
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
              minWidth={720}
              head={
                <>
                  <Th>{t("accounts.username")}</Th>
                  <Th>{t("sources.owner")}</Th>
                  <Th align="right">{t("accounts.reels")}</Th>
                  <Th align="right">{t("accounts.followers")}</Th>
                  <Th>{t("accounts.lastScraped")}</Th>
                  <Th>{t("accounts.status")}</Th>
                  <Th align="right" />
                </>
              }
            >
              {rows.map((a) => {
                const comp = a.owner_type === "competitor";
                return (
                  <tr key={a.id} className="text-navy">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {a.profile_pic_url && (
                          <img
                            src={a.profile_pic_url}
                            alt=""
                            className="h-7 w-7 rounded-full object-cover"
                          />
                        )}
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-navy">@{a.username}</div>
                          {a.display_name && (
                            <div className="truncate text-xs text-muted">{a.display_name}</div>
                          )}
                        </div>
                      </div>
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
                    <td className="px-4 py-3 text-right tabular-nums">{a.reel_count ?? 0}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatCount(a.followers_count)}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted">
                      {a.last_scraped_at ? formatDate(a.last_scraped_at) : t("accounts.never")}
                    </td>
                    <td className="px-4 py-3">
                      <StatusToggle
                        onClick={() => toggle.mutate({ id: a.id, is_active: !a.is_active })}
                        title={t("manage.toggleHint")}
                      >
                        <Badge
                          className={
                            a.is_active ? "bg-success/10 text-success" : "bg-surface text-muted"
                          }
                        >
                          {a.is_active ? t("accounts.active") : t("accounts.inactive")}
                        </Badge>
                      </StatusToggle>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <RowActions>
                        <RowAction
                          tone="danger"
                          onClick={() => {
                            if (confirm(t("accounts.confirmRemove"))) remove.mutate(a.id);
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

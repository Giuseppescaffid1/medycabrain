import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  addAccount,
  deleteAccount,
  fetchAccounts,
  updateAccount,
} from "../api/endpoints";
import { Badge, Button, Skeleton, fieldCls } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";
import { formatCount, formatDate } from "../lib/utils";

export default function Accounts() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");

  const { data, isLoading } = useQuery({ queryKey: ["accounts"], queryFn: fetchAccounts });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["accounts"] });

  const add = useMutation({
    mutationFn: (u: string) => addAccount(u),
    onSuccess: () => {
      setUsername("");
      setError("");
      invalidate();
    },
    onError: () => setError(t("common.error")),
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

  return (
    <PageTransition>
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-4 sm:px-6">
        <h1 className="text-xl font-bold text-heading">{t("accounts.title")}</h1>
      </div>

      <div className="flex-1 px-4 py-4 sm:px-6 sm:py-5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (clean(username)) add.mutate(clean(username));
          }}
          className="mb-6 flex max-w-md gap-2"
        >
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder={t("accounts.addPlaceholder")}
            className={fieldCls + " min-w-0 flex-1"}
          />
          <Button type="submit" loading={add.isPending}>
            {t("accounts.add")}
          </Button>
        </form>
        {error && <p className="mb-4 text-sm font-semibold text-danger">⚠ {error}</p>}

        {isLoading ? (
          <Skeleton className="h-64" />
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-surface text-left text-xs font-bold uppercase tracking-wider text-muted">
                <tr>
                  <th className="px-4 py-3">{t("accounts.username")}</th>
                  <th className="px-4 py-3">{t("accounts.reels")}</th>
                  <th className="px-4 py-3">{t("accounts.followers")}</th>
                  <th className="px-4 py-3">{t("accounts.lastScraped")}</th>
                  <th className="px-4 py-3">{t("accounts.status")}</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data?.map((a) => (
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
                        <div>
                          <div className="font-semibold text-navy">@{a.username}</div>
                          {a.display_name && (
                            <div className="text-xs text-muted">{a.display_name}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{a.reel_count ?? 0}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{formatCount(a.followers_count)}</td>
                    <td className="px-4 py-3 text-xs text-muted">
                      {a.last_scraped_at ? formatDate(a.last_scraped_at) : t("accounts.never")}
                    </td>
                    <td className="px-4 py-3">
                      <button onClick={() => toggle.mutate({ id: a.id, is_active: !a.is_active })}>
                        <Badge
                          className={
                            a.is_active
                              ? "bg-success/10 text-success"
                              : "bg-surface text-muted"
                          }
                        >
                          {a.is_active ? t("accounts.active") : t("accounts.inactive")}
                        </Badge>
                      </button>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => {
                          if (confirm(t("accounts.confirmRemove"))) remove.mutate(a.id);
                        }}
                        className="text-xs font-semibold text-muted hover:text-danger"
                      >
                        {t("accounts.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
    </PageTransition>
  );
}

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  addAccount,
  deleteAccount,
  fetchAccounts,
  updateAccount,
} from "../api/endpoints";
import { Badge, Button, Spinner } from "../components/ui/primitives";
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
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-xl font-bold text-white">{t("accounts.title")}</h1>
      </div>

      <div className="flex-1 px-6 py-5">
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
            className="flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
          />
          <Button type="submit" disabled={add.isPending}>
            {t("accounts.add")}
          </Button>
        </form>
        {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

        {isLoading ? (
          <Spinner />
        ) : (
          <div className="overflow-hidden rounded-xl border border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-900 text-left text-xs uppercase text-zinc-500">
                <tr>
                  <th className="px-4 py-3">{t("accounts.username")}</th>
                  <th className="px-4 py-3">{t("accounts.reels")}</th>
                  <th className="px-4 py-3">{t("accounts.followers")}</th>
                  <th className="px-4 py-3">{t("accounts.lastScraped")}</th>
                  <th className="px-4 py-3">{t("accounts.status")}</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {data?.map((a) => (
                  <tr key={a.id} className="text-zinc-300">
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
                          <div className="font-medium text-white">@{a.username}</div>
                          {a.display_name && (
                            <div className="text-xs text-zinc-500">{a.display_name}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">{a.reel_count ?? 0}</td>
                    <td className="px-4 py-3">{formatCount(a.followers_count)}</td>
                    <td className="px-4 py-3 text-xs text-zinc-500">
                      {a.last_scraped_at ? formatDate(a.last_scraped_at) : t("accounts.never")}
                    </td>
                    <td className="px-4 py-3">
                      <button onClick={() => toggle.mutate({ id: a.id, is_active: !a.is_active })}>
                        <Badge
                          className={
                            a.is_active
                              ? "bg-green-600/20 text-green-400"
                              : "bg-zinc-700 text-zinc-400"
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
                        className="text-xs text-zinc-500 hover:text-red-400"
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
  );
}

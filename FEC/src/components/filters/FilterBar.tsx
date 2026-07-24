import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchAccounts, fetchClusters, type Scope } from "../../api/endpoints";
import type { ReelFilters } from "../../api/endpoints";

const FORMATS = [
  "talking_head", "voiceover", "tutorial", "testimonianza",
  "text_overlay", "intervista", "altro",
];

export function FilterBar({
  filters,
  onChange,
  scope = "competitor",
}: {
  filters: ReelFilters;
  onChange: (f: ReelFilters) => void;
  scope?: Scope;
}) {
  const { t } = useTranslation();
  const ownerType = scope === "medyca" ? "owned" : "competitor";
  const { data: allAccounts } = useQuery({ queryKey: ["accounts"], queryFn: fetchAccounts });
  const accounts = allAccounts?.filter((a) => a.owner_type === ownerType);
  const { data: clusters } = useQuery({
    queryKey: ["clusters", scope],
    queryFn: () => fetchClusters(scope),
  });

  const set = (patch: Partial<ReelFilters>) => onChange({ ...filters, ...patch, page: 1 });

  const selectCls =
    "h-10 shrink-0 rounded-full border border-border bg-white px-4 text-sm text-navy outline-none transition focus:border-secondary";

  return (
    <div className="-mx-4 flex flex-nowrap items-center gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0 sm:pb-0">
      <select
        className={selectCls}
        value={filters.account ?? ""}
        onChange={(e) => set({ account: e.target.value ? Number(e.target.value) : undefined })}
      >
        <option value="">{t("library.allAccounts")}</option>
        {accounts?.map((a) => (
          <option key={a.id} value={a.id}>@{a.username}</option>
        ))}
      </select>

      <select
        className={selectCls}
        value={filters.content_format ?? ""}
        onChange={(e) => set({ content_format: e.target.value || undefined })}
      >
        <option value="">{t("library.allFormats")}</option>
        {FORMATS.map((f) => (
          <option key={f} value={f}>{t(`reel.${f}`, f)}</option>
        ))}
      </select>

      <select
        className={selectCls}
        value={filters.cluster ?? ""}
        onChange={(e) => set({ cluster: e.target.value ? Number(e.target.value) : undefined })}
      >
        <option value="">{t("library.allClusters")}</option>
        {clusters?.map((c) => (
          <option key={c.id} value={c.id}>{c.label_it}</option>
        ))}
      </select>

      <select
        className={selectCls}
        value={filters.ordering ?? "-posted_at"}
        onChange={(e) => set({ ordering: e.target.value })}
      >
        <option value="-posted_at">{t("library.sortRecent")}</option>
        <option value="-view_count">{t("library.sortViews")}</option>
        <option value="-like_count">{t("library.sortLikes")}</option>
      </select>

      <ChipToggle
        active={!!filters.favorite}
        onClick={() => set({ favorite: filters.favorite ? undefined : true })}
      >
        ⭐ {t("library.onlyFavorites")}
      </ChipToggle>
      <ChipToggle
        active={!!filters.inspiration}
        onClick={() => set({ inspiration: filters.inspiration ? undefined : true })}
      >
        💡 {t("library.onlyInspiration")}
      </ChipToggle>

      <button
        onClick={() =>
          onChange({ search: filters.search, ordering: "-posted_at", page: 1 })
        }
        className="h-10 shrink-0 whitespace-nowrap rounded-full px-3 text-sm font-semibold text-muted transition hover:bg-surface hover:text-navy"
      >
        {t("library.reset")}
      </button>
    </div>
  );
}

function ChipToggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "h-10 shrink-0 whitespace-nowrap rounded-full border px-4 text-sm font-semibold transition " +
        (active
          ? "border-secondary bg-surface text-heading"
          : "border-border bg-white text-muted hover:text-navy")
      }
    >
      {children}
    </button>
  );
}

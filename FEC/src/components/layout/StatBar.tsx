import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchStats } from "../../api/endpoints";
import type { Scope } from "../../api/endpoints";

export function StatBar({ scope = "competitor" }: { scope?: Scope }) {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["stats"], queryFn: fetchStats });
  if (!data) return null;
  const s = scope === "medyca" ? data.medyca : data.competitor;

  const items = [
    { label: t("stats.reels"), value: s.reels },
    { label: t("stats.transcribed"), value: s.transcribed },
    { label: t("stats.enriched"), value: s.enriched },
    { label: t("stats.clusters"), value: s.clusters },
  ];

  return (
    <div className="-mx-4 flex flex-nowrap gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:gap-3 sm:px-0">
      {items.map((it) => (
        <div
          key={it.label}
          className="shrink-0 whitespace-nowrap rounded-full border border-border bg-surface px-3 py-1.5"
        >
          <span className="text-sm font-bold text-navy">{it.value}</span>
          <span className="ml-1.5 text-xs font-semibold text-muted">{it.label}</span>
        </div>
      ))}
    </div>
  );
}

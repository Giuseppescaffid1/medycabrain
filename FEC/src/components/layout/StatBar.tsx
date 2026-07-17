import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchStats } from "../../api/endpoints";

export function StatBar() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["stats"], queryFn: fetchStats });
  if (!data) return null;

  const items = [
    { label: t("stats.accounts"), value: data.accounts },
    { label: t("stats.reels"), value: data.reels },
    { label: t("stats.transcribed"), value: data.transcribed },
    { label: t("stats.enriched"), value: data.enriched },
    { label: t("stats.clusters"), value: data.clusters },
    { label: t("stats.favorites"), value: data.favorites },
  ];

  return (
    <div className="flex flex-wrap gap-3">
      {items.map((it) => (
        <div
          key={it.label}
          className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-1.5"
        >
          <span className="text-sm font-semibold text-white">{it.value}</span>
          <span className="ml-1.5 text-xs text-zinc-500">{it.label}</span>
        </div>
      ))}
    </div>
  );
}

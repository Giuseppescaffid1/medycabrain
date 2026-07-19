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
    <div className="flex flex-wrap gap-3">
      {items.map((it) => (
        <div key={it.label} className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-1.5">
          <span className="text-sm font-semibold text-white">{it.value}</span>
          <span className="ml-1.5 text-xs text-zinc-500">{it.label}</span>
        </div>
      ))}
    </div>
  );
}

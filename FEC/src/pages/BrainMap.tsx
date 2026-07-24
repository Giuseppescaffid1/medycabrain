import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Scope } from "../api/endpoints";

/**
 * The second-brain constellation graph — the pipeline DAG + theme clusters
 * with their reels/blog + competitor opportunities, rendered in the ~/brain
 * force-graph style. graph.html is a self-contained canvas app served from
 * /public; it reads the auth token from localStorage (same origin).
 */
export default function BrainMap() {
  const { t } = useTranslation();
  const [scope, setScope] = useState<Scope>("medyca");

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <div>
          <h1 className="text-lg font-bold text-white">{t("map.title")}</h1>
          <p className="text-xs text-zinc-500">{t("map.subtitle")}</p>
        </div>
        <div className="inline-flex rounded-lg border border-zinc-800 bg-zinc-900 p-1">
          {(["medyca", "competitor"] as Scope[]).map((s) => (
            <button
              key={s}
              onClick={() => setScope(s)}
              className={
                "rounded-md px-3 py-1 text-sm font-medium " +
                (scope === s ? "bg-indigo-600 text-white" : "text-zinc-400 hover:text-zinc-200")
              }
            >
              {t(`scope.${s}`)}
            </button>
          ))}
        </div>
      </div>
      <iframe
        key={scope}
        title="brain-graph"
        src={`/graph.html?scope=${scope}`}
        className="min-h-0 flex-1 border-0"
      />
    </div>
  );
}

import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Scope } from "../api/endpoints";
import { PageTransition } from "../components/ui/motion";

/**
 * The second-brain constellation graph — the pipeline DAG + theme clusters
 * with their reels/blog + competitor opportunities, rendered in the ~/brain
 * force-graph style. graph.html is a self-contained canvas app served from
 * /public; it reads the auth token from localStorage (same origin). The dark
 * navy canvas inside the light app is deliberate: observatory mode.
 */
export default function BrainMap() {
  const { t } = useTranslation();
  const [scope, setScope] = useState<Scope>("medyca");

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="flex flex-col gap-3 border-b border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div>
            <h1 className="text-lg font-bold text-heading">{t("map.title")}</h1>
            <p className="text-xs text-muted">{t("map.subtitle")}</p>
          </div>
          <div className="inline-flex self-start rounded-full border border-border bg-white p-1 sm:self-auto">
            {(["medyca", "competitor"] as Scope[]).map((s) => (
              <button
                key={s}
                onClick={() => setScope(s)}
                className={
                  "rounded-full px-4 py-1 text-sm font-semibold transition " +
                  (scope === s ? "bg-secondary text-white" : "text-muted hover:text-navy")
                }
              >
                {t(`scope.${s}`)}
              </button>
            ))}
          </div>
        </div>
        <div className="min-h-0 flex-1 lg:p-6">
          <div className="h-full overflow-hidden lg:rounded-3xl lg:border lg:border-border lg:shadow-card">
            <iframe
              key={scope}
              title="brain-graph"
              src={`/graph.html?scope=${scope}`}
              className="h-full w-full border-0"
            />
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

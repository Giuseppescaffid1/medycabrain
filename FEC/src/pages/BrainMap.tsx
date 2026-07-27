import { useState } from "react";
import { useTranslation } from "react-i18next";
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

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="flex flex-col gap-3 border-b border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div>
            <h1 className="text-lg font-bold text-heading">{t("map.title")}</h1>
            <p className="text-xs text-muted">{t("map.subtitle")}</p>
          </div>
        </div>
        <div className="min-h-0 flex-1 lg:p-6">
          <div className="h-full overflow-hidden lg:rounded-3xl lg:border lg:border-border lg:shadow-card">
            <iframe
              title="brain-graph"
              // graph.html is a static file with no content hash, so a browser
              // will happily keep serving yesterday's version. Tie it to the build.
              src={`/graph.html?v=${__BUILD_ID__}`}
              className="h-full w-full border-0"
            />
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

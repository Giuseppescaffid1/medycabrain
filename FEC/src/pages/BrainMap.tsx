import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchGraph, type GraphNode } from "../api/graph";
import { BrainGraph } from "../components/graph/BrainGraph";
import { NodePanel } from "../components/graph/NodePanel";
import { Skeleton } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";

/**
 * The second brain, as a map you can actually click.
 *
 * Three worlds — Medyca, the competition, and the opportunities between them —
 * with only the themes drawn at rest. Everything lives in React now: the old
 * iframe carried its own stylesheet, its own language and no cache busting,
 * and browsers happily served yesterday's copy of it.
 */
export default function BrainMap() {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["brain-graph"], queryFn: fetchGraph });

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-4 py-3 sm:px-6">
          <h1 className="text-lg font-bold text-heading">{t("map.title")}</h1>
          <p className="text-xs text-muted">{t("map.subtitle")}</p>
        </div>

        <div className="min-h-0 flex-1 lg:p-6">
          <div className="relative h-full overflow-hidden lg:rounded-3xl lg:border lg:border-border lg:shadow-card">
            {isLoading || !data ? (
              <Skeleton className="h-full w-full rounded-none" />
            ) : (
              <>
                <BrainGraph
                  data={data}
                  onSelect={setSelected}
                  selectedId={selected?.id ?? null}
                />
                <NodePanel
                  node={selected}
                  data={data}
                  onClose={() => setSelected(null)}
                  onSelect={setSelected}
                />
              </>
            )}
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

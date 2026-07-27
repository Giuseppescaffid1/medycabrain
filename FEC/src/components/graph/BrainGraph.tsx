import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import cytoscape from "cytoscape";
import type { Core, ElementDefinition, NodeSingular } from "cytoscape";
import type { GraphNode, GraphPayload } from "../../api/graph";
import { childPositions, worldPositions } from "./layout";

/**
 * The second brain as three worlds.
 *
 * Only the hubs and their themes are drawn at rest — roughly 25 well-spaced
 * elements. The previous canvas drew all hundred at once, which at fit-zoom
 * made a reel two pixels wide with a thirty-eight pixel tap target: three
 * nodes competed for every click and one won arbitrarily. Opening a theme is
 * what reveals its reels and articles, at a size that can actually be hit.
 */

const HUE = {
  owned: "#5FA8FF",
  competitor: "#F0B25C",
  opportunity: "#E77C81",
  theme_owned: "#8FB8F0",
  theme_competitor: "#E0A96D",
  blog: "#67C99A",
  custom: "#C9A0E8",
} as const;

function colourOf(n: GraphNode): string {
  if (n.group === "hub" || n.group === "opportunity")
    return HUE[(n.owner as keyof typeof HUE) in HUE ? (n.owner as "owned") : "owned"];
  if (n.group === "blog") return HUE.blog;
  if (n.group === "custom") return HUE.custom;
  if (n.group === "theme")
    return n.owner === "competitor" ? HUE.theme_competitor : HUE.theme_owned;
  return n.owner === "competitor" ? HUE.competitor : HUE.owned;
}

const SIZE: Record<string, number> = {
  hub: 74,
  theme: 44,
  opportunity: 46,
  custom: 42,
  reel: 30,
  blog: 30,
};

export function BrainGraph({
  data,
  onSelect,
  selectedId,
}: {
  data: GraphPayload;
  onSelect: (n: GraphNode | null) => void;
  selectedId: string | null;
}) {
  const { t } = useTranslation();
  const boxRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const byId = useMemo(
    () => Object.fromEntries(data.nodes.map((n) => [n.id, n])),
    [data.nodes]
  );
  const childrenOf = useMemo(() => {
    const m: Record<string, GraphNode[]> = {};
    data.nodes.forEach((n) => {
      if (n.parent) (m[n.parent] = m[n.parent] ?? []).push(n);
    });
    return m;
  }, [data.nodes]);

  // ── build the resting graph: hubs + their direct children only ──────────
  useEffect(() => {
    if (!boxRef.current) return;
    const pos = worldPositions(data.nodes);
    const visible = data.nodes.filter((n) => n.group === "hub" || pos[n.id]);
    const visibleIds = new Set(visible.map((n) => n.id));

    const elements: ElementDefinition[] = [
      ...visible.map((n) => ({
        data: {
          id: n.id,
          label: n.label,
          group: n.group,
          colour: colourOf(n),
          size: SIZE[n.group] ?? 30,
          kids: (childrenOf[n.id] ?? []).length,
        },
        position: pos[n.id],
      })),
      ...data.edges
        .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
        .map((e, i) => ({
          data: {
            id: `e${i}`,
            source: e.source,
            target: e.target,
            rel: e.rel,
            flow: e.kind === "flow" ? 1 : 0,
          },
        })),
    ];

    const cy = cytoscape({
      container: boxRef.current,
      elements,
      minZoom: 0.15,
      maxZoom: 2.5,
      wheelSensitivity: 0.25,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(colour)",
            width: "data(size)",
            height: "data(size)",
            label: "data(label)",
            color: "#E8F0FB",
            "font-size": 13,
            "font-weight": 600,
            "text-valign": "bottom",
            "text-margin-y": 6,
            "text-wrap": "wrap",
            "text-max-width": "140px",
            "text-outline-color": "#0D1930",
            "text-outline-width": 3,
            "border-width": 2,
            "border-color": "#0D1930",
            "transition-property": "width height border-width",
            "transition-duration": 180,
          },
        },
        {
          selector: 'node[group = "hub"]',
          style: { "font-size": 17, "text-valign": "center", "text-margin-y": 0,
                   "text-outline-width": 4 },
        },
        {
          selector: "node:selected",
          style: { "border-width": 5, "border-color": "#FFFFFF" },
        },
        {
          selector: "node.dimmed",
          style: { opacity: 0.25 },
        },
        {
          selector: "edge",
          style: {
            width: 1.4,
            "line-color": "#3D5980",
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#3D5980",
            "arrow-scale": 0.8,
            opacity: 0.7,
          },
        },
        {
          selector: "edge[flow = 1]",
          style: {
            "line-color": "#E77C81",
            "target-arrow-color": "#E77C81",
            "line-style": "dashed",
            label: "data(rel)",
            "font-size": 10,
            color: "#A9BCD8",
            "text-rotation": "autorotate",
            "text-background-color": "#0D1930",
            "text-background-opacity": 0.85,
            "text-background-padding": "2px",
          },
        },
      ],
      layout: { name: "preset" },
    });

    cy.on("tap", "node", (evt) => {
      const node = evt.target as NodeSingular;
      const n = byId[node.id()];
      if (!n) return;
      onSelect(n);
      if ((childrenOf[n.id] ?? []).length) toggle(n.id);
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) onSelect(null);
    });
    cy.on("mouseover", "node", () => {
      if (boxRef.current) boxRef.current.style.cursor = "pointer";
    });
    cy.on("mouseout", "node", () => {
      if (boxRef.current) boxRef.current.style.cursor = "default";
    });

    cyRef.current = cy;
    // Exposed on purpose: lets a browser session (or an automated check)
    // inspect what is actually rendered and where, which is how the old
    // click problem was measured in the first place.
    (window as unknown as { __cy?: Core }).__cy = cy;

    // Fit, but never below the zoom that keeps a theme tappable. On a phone a
    // plain fit shrank themes to 7px — small enough that a finger covers three
    // of them, which is the failure this whole rewrite was about.
    const readable = () => {
      const pad = window.innerWidth < 640 ? 30 : 90;
      cy.fit(undefined, pad);
      const smallest = Math.min(...cy.nodes().map((n) => n.renderedWidth()));
      const MIN_PX = window.innerWidth < 640 ? 22 : 16;
      if (smallest > 0 && smallest < MIN_PX) {
        cy.zoom({ level: cy.zoom() * (MIN_PX / smallest), renderedPosition: { x: 0, y: 0 } });
        const home = cy.getElementById("root:medyca");
        if (home.length) cy.center(home);
      }
    };
    readable();
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  /** Reveal or hide a theme's reels and articles. */
  const toggle = (id: string) => {
    const cy = cyRef.current;
    if (!cy) return;
    const kids = childrenOf[id] ?? [];
    if (!kids.length) return;

    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        cy.remove(cy.nodes().filter((n) => kids.some((k) => k.id === n.id())));
      } else {
        next.add(id);
        const parent = cy.getElementById(id);
        const hubId = byId[id]?.parent;
        const hub = hubId ? cy.getElementById(hubId) : null;
        const p = parent.position();
        const h = hub && hub.length ? hub.position() : { x: 0, y: 0 };
        const spots = childPositions(p, h, kids.length);
        kids.forEach((k, i) => {
          if (cy.getElementById(k.id).length) return;
          cy.add({
            group: "nodes",
            data: {
              id: k.id,
              label: k.label,
              group: k.group,
              colour: colourOf(k),
              size: SIZE[k.group] ?? 30,
              kids: 0,
            },
            position: spots[i],
          });
          cy.add({
            group: "edges",
            data: { id: `x-${id}-${k.id}`, source: id, target: k.id, flow: 0 },
          });
        });
        cy.animate({ fit: { eles: parent.closedNeighborhood(), padding: 120 } },
                   { duration: 420 });
      }
      return next;
    });
  };

  // keep the canvas selection in step with the panel
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().unselect();
    if (selectedId) cy.getElementById(selectedId).select();
  }, [selectedId]);

  return (
    <div className="relative h-full w-full">
      {/* touch-action:none — without it the browser claims the gesture as a
          scroll and Cytoscape never sees the tap, so nothing is selectable
          on a phone. */}
      <div
        ref={boxRef}
        className="h-full w-full touch-none select-none"
        style={{ background: "#0D1930" }}
      />

      <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap gap-2 sm:left-4 sm:top-4">
        {(
          [
            ["owned", t("map.legendMedyca")],
            ["competitor", t("map.legendCompetitor")],
            ["opportunity", t("map.legendOpportunity")],
          ] as const
        ).map(([k, label]) => (
          <span
            key={k}
            className="flex items-center gap-1.5 rounded-full bg-navy/70 px-2.5 py-1 text-[11px] font-semibold text-white/85 backdrop-blur"
          >
            <span className="h-2 w-2 rounded-full" style={{ background: HUE[k] }} />
            {label}
          </span>
        ))}
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 rounded-full bg-navy/70 px-3 py-1.5 text-[11px] text-white/70 backdrop-blur sm:bottom-4 sm:left-4">
        {t("map.hint")}
      </div>

      <button
        onClick={() => {
          const cy = cyRef.current;
          if (!cy) return;
          cy.animate({ fit: { eles: cy.elements(), padding: window.innerWidth < 640 ? 30 : 90 } },
                     { duration: 350 });
        }}
        className="absolute bottom-3 right-3 rounded-full bg-navy/70 px-3 py-1.5 text-[11px] font-semibold text-white/85 backdrop-blur transition hover:bg-navy/90 sm:bottom-4 sm:right-4"
      >
        {t("map.recenter")}
      </button>
    </div>
  );
}

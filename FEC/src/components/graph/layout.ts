import type { GraphNode } from "../../api/graph";

/**
 * Deterministic positions for the three worlds.
 *
 * Medyca on the left, competitors on the right, opportunities below — each
 * hub owning a region so the two sides never reach across each other. Preset
 * rather than force-directed on purpose: a map the client returns to should
 * look the same every time, and a simulation that settles differently on each
 * visit makes it impossible to remember where anything was.
 */
export interface Pos {
  x: number;
  y: number;
}

const ANCHORS: Record<string, Pos> = {
  "root:medyca": { x: -900, y: -120 },
  "root:competitor": { x: 900, y: -120 },
  "root:opportunity": { x: 0, y: 620 },
};

/** Themes in the first ring of a hub, and how many more each outer ring takes.
 *  One arc could not hold 307 competitor themes: they landed ~8 px apart and
 *  overlapped. Rings keep the layout deterministic and every dot clickable. */
const FIRST_RING = 24;
const RING_GROWTH = 8;
const RING_GAP = 90;

/** Themes fan into the half-plane pointing away from the centre, in
 *  concentric rings once there are more than fit on one arc. */
export function worldPositions(nodes: GraphNode[]): Record<string, Pos> {
  const pos: Record<string, Pos> = {};
  const hubs = nodes.filter((n) => n.group === "hub");

  hubs.forEach((h) => {
    pos[h.id] = ANCHORS[h.id] ?? { x: 0, y: 0 };
  });

  hubs.forEach((h) => {
    const a = pos[h.id];
    const kids = nodes.filter((n) => n.parent === h.id);
    if (!kids.length) return;
    const outward = a.x === 0 ? Math.PI / 2 : a.x < 0 ? Math.PI : 0;
    const spread = Math.PI * 1.05;

    let placed = 0;
    for (let ring = 0; placed < kids.length; ring++) {
      const capacity = FIRST_RING + ring * RING_GROWTH;
      const inRing = kids.slice(placed, placed + capacity);
      // Radius grows with the count so a crowded ring spreads instead of
      // stacking: spacing is what makes a node clickable.
      const radius = 340 + Math.min(inRing.length, 16) * 26 + ring * RING_GAP;
      // Each ring has its own count, hence its own step: dots do not line
      // up radially from one ring to the next.
      const step = inRing.length > 1 ? spread / (inRing.length - 1) : 0;
      inRing.forEach((k, i) => {
        const t =
          kids.length === 1
            ? outward
            : inRing.length === 1
              ? outward
              : outward - spread / 2 + step * i;
        pos[k.id] = { x: a.x + Math.cos(t) * radius, y: a.y + Math.sin(t) * radius };
      });
      placed += inRing.length;
    }
  });

  return pos;
}

/** Where a theme's children sit once it is opened: a ring around it, pushed
 *  away from its hub so labels do not fall back over the parent. */
export function childPositions(
  parent: Pos,
  hub: Pos,
  count: number
): Pos[] {
  if (count === 0) return [];
  const away = Math.atan2(parent.y - hub.y, parent.x - hub.x);
  const radius = 130 + count * 16;
  const spread = Math.min(Math.PI * 1.3, 0.55 * count);
  return Array.from({ length: count }, (_, i) => {
    const t =
      count === 1 ? away : away - spread / 2 + (spread * i) / (count - 1);
    return { x: parent.x + Math.cos(t) * radius, y: parent.y + Math.sin(t) * radius };
  });
}

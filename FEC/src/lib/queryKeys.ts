import type { QueryClient } from "@tanstack/react-query";

/**
 * Every react-query prefix that can show a reel. One list, so that changing a
 * reel (favourite, exclude, tag, note) refreshes every view that shows it.
 * The drawer used to invalidate only `reel` and `reels`: the Workspace, the
 * Timeline and the cluster page kept showing the old star until a reload.
 */
export const REEL_VIEW_KEYS = [
  "reels",
  "workspace",
  "timeline",
  "cluster-reels",
  "topic-matches",
  "tags",
  "stats",
  "an-top",
  "an-overview",
  "an-time",
  "an-clusters",
] as const;

export function invalidateReelViews(qc: QueryClient, reelId?: number | null) {
  if (reelId != null) qc.invalidateQueries({ queryKey: ["reel", reelId] });
  REEL_VIEW_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

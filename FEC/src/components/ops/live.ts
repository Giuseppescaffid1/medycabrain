import { useEffect, useState } from "react";

/** Durations, in the one form the whole operations view uses. */
export const fmtDuration = (s: number) =>
  s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;

/**
 * A second hand for anything whose duration is still growing.
 *
 * Elapsed times are measured on the server, but the page polls every five
 * seconds: without a local tick the numbers would jump in steps and a bar
 * that is genuinely advancing would look stuck between polls.
 */
export function useTicker(active: boolean) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [active]);
}

/** Server-measured seconds, carried forward to now. */
export const elapsedNow = (seconds: number, updatedAt?: number) =>
  Math.max(0, seconds + (updatedAt ? Math.round((Date.now() - updatedAt) / 1000) : 0));

import { lazy, type ComponentType } from "react";

/**
 * A lazily loaded page that survives a deploy made while the tab was open.
 *
 * Each build writes new file names and removes the previous ones, so a tab
 * that has been open across a deploy asks for a file that no longer exists.
 * The import rejects, nothing catches it, and the app is left half-rendered —
 * which is what "the side menu disappeared" looks like from the outside.
 *
 * The fix is to reload once, which fetches the current build. The flag makes
 * it once: if the page is genuinely broken, a reload loop would hide the real
 * error instead of surfacing it.
 */
const FLAG = "medyca:chunk-reloaded";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyPage<T extends ComponentType<any>>(
  load: () => Promise<{ default: T }>
) {
  return lazy(() =>
    load()
      .then((mod) => {
        sessionStorage.removeItem(FLAG);
        return mod;
      })
      .catch((err) => {
        if (!sessionStorage.getItem(FLAG)) {
          sessionStorage.setItem(FLAG, "1");
          window.location.reload();
          // The reload takes over; never resolve, so nothing renders meanwhile.
          return new Promise<{ default: T }>(() => {});
        }
        throw err;
      })
  );
}

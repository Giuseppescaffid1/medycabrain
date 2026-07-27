import { useCallback, useState } from "react";

/**
 * Copy that works on this deployment.
 *
 * The platform is served over plain HTTP, and `navigator.clipboard` only
 * exists in a secure context — so every copy button was silently doing
 * nothing, the optional chaining swallowing the failure. Falls back to the
 * old execCommand path, which still works outside HTTPS.
 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* fall through: permission denied or blocked */
    }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    // Keep it off-screen but selectable; iOS needs it non-readonly and visible
    // to the layout engine, hence the fixed position rather than display:none.
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/** Copy with a short confirmation, because a button that does nothing
 *  visible reads as broken even when it worked. */
export function useCopy(resetMs = 1800) {
  const [state, setState] = useState<"idle" | "done" | "error">("idle");
  const copy = useCallback(
    async (text: string) => {
      const ok = await copyText(text);
      setState(ok ? "done" : "error");
      setTimeout(() => setState("idle"), resetMs);
      return ok;
    },
    [resetMs]
  );
  return { copy, state };
}

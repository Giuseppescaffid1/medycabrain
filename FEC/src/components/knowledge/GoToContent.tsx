import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, fieldCls } from "../ui/primitives";

/**
 * "Vai al contenuto": the client pastes a reference the MCP cited — `blog:843`
 * or `reel:199` — and lands on that content's card inside the brain.
 *
 * The parsing is deliberately forgiving. The MCP only ever emits `kind:id`
 * (`server.py`), but the client's own Claude prepends a citation number, so what
 * gets pasted is `[2] blog:843` or `blog 2:843`. That number is not ours and
 * must be thrown away: we keep the kind word and the id after the colon, and
 * ignore everything in between.
 */
export type ContentRef = { kind: "reel" | "blog"; id: number };

export function parseRef(raw: string): ContentRef | null {
  // The MCP's own link (`<base>/content/blog/843`, the `apri_nel_brain` field)
  // is what the client copies most often, and it has no colon: the `kind:id`
  // pattern below rejected the very format the MCP emits.
  const link = raw.match(/\/content\/(reel|blog)\/(\d+)(?![\d])/i);
  if (link) {
    const id = parseInt(link[2], 10);
    if (Number.isInteger(id) && id > 0) {
      return { kind: link[1].toLowerCase() === "reel" ? "reel" : "blog", id };
    }
  }
  const m = raw.trim().match(/(reel|blog|articol[oi]|article)\b[^:]*:\s*(\d+)/i);
  if (!m) return null;
  const id = parseInt(m[2], 10);
  if (!Number.isInteger(id) || id <= 0) return null;
  // "articolo"/"article" are the words the client sees for a blog post; they
  // all resolve to the blog card.
  return { kind: /^reel/i.test(m[1]) ? "reel" : "blog", id };
}

export function GoToContent({ onOpen }: { onOpen: (ref: ContentRef) => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [error, setError] = useState(false);

  const go = () => {
    const ref = parseRef(value);
    if (!ref) {
      setError(true);
      return;
    }
    setError(false);
    // Opens in place, over the chat: navigating to /content/... unmounted the
    // page and the whole conversation with it. The route stays for links
    // opened from outside (the MCP's `apri_nel_brain`).
    onOpen(ref);
  };

  return (
    <div>
      <label htmlFor="goto-content" className="mb-1.5 block text-xs font-semibold text-muted">
        {t("content.gotoLabel")}
      </label>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          go();
        }}
        className="flex flex-col gap-2 sm:flex-row sm:items-center"
      >
        <input
          id="goto-content"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            if (error) setError(false);
          }}
          placeholder={t("content.gotoPlaceholder")}
          aria-invalid={error}
          className={fieldCls + " min-w-0 flex-1"}
        />
        <Button type="submit" disabled={!value.trim()} className="shrink-0">
          {t("content.gotoButton")}
        </Button>
      </form>
      {/* Brand red doubles as the danger colour, so the error carries an icon and
          plain text and never leans on colour alone. */}
      {error && (
        <p role="alert" className="mt-1.5 text-xs font-semibold text-danger">
          ⚠ {t("content.gotoError")}
        </p>
      )}
    </div>
  );
}

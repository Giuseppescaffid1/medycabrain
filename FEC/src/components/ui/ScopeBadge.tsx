import { useTranslation } from "react-i18next";
import type { Scope } from "../../api/endpoints";

/**
 * Whose content am I looking at? Every scoped page answers that in the same
 * place, with the same colour, so the client never has to reconstruct it from
 * the URL or the sidebar. Blue is Medyca, amber is the competition —
 * the same coding the constellation map uses.
 */
export function ScopeBadge({ scope }: { scope: Scope }) {
  const { t } = useTranslation();
  const own = scope === "medyca";
  return (
    <span
      className={
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-bold " +
        (own
          ? "border-secondary/40 bg-secondary/10 text-secondary"
          : "border-warning/40 bg-warning/10 text-warning")
      }
    >
      <span
        className={"h-2 w-2 rounded-full " + (own ? "bg-secondary" : "bg-warning")}
        aria-hidden
      />
      {t(`scope.${scope}`)}
      <span className="font-medium opacity-70">
        · {t(own ? "scope.medycaHint" : "scope.competitorHint")}
      </span>
    </span>
  );
}

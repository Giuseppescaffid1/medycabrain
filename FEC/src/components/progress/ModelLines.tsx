import { useTranslation } from "react-i18next";
import { Badge } from "../ui/primitives";
import type { ProgressItem } from "../../api/progress";
import { elapsedNow, fmtDuration } from "../ops/live";
import { fmtNum } from "./format";

/**
 * "Chi sta lavorando adesso": one line per open model call.
 *
 * The state is always written in words (in coda, sta leggendo, sta scrivendo)
 * and who works is always "locale" or "remoto" in a badge, never a colour only.
 * Two lines per item so a 380 px screen never scrolls sideways: the name is cut
 * with dots on the first, the details wrap on the second.
 */
export function ModelLines({
  items,
  more,
  updatedAt,
}: {
  items: ProgressItem[];
  more: number;
  updatedAt?: number;
}) {
  const { t } = useTranslation();
  if (items.length === 0) return null;
  return (
    <ul className="mt-3 space-y-2" aria-label={t("progress.workingOn")}>
      {items.map((it, i) => (
        <li key={`${it.label}-${i}`} className="rounded-lg bg-white px-3 py-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate font-semibold text-navy">
              {it.label || it.process_label || "—"}
            </span>
            <Badge className={it.is_local ? "bg-secondary/10 text-secondary" : "bg-warning/10 text-warning"}>
              {it.is_local ? t("progress.local") : t("progress.remote")}
            </Badge>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-muted">
            <span className="font-semibold text-navy">
              {it.state === "waiting"
                ? t("progress.state.waiting", {
                    duration: fmtDuration(elapsedNow(it.seconds, updatedAt)),
                  })
                : t(`progress.state.${it.state}`)}
            </span>
            {it.model && <span className="max-w-full truncate">{it.model}</span>}
            {it.state !== "waiting" && (
              <span className="tabular-nums">{fmtDuration(elapsedNow(it.seconds, updatedAt))}</span>
            )}
            {it.tokens != null && it.tokens > 0 && (
              <span className="tabular-nums">{t("progress.tokens", { n: it.tokens })}</span>
            )}
            {it.tokens_per_second != null && (
              <span className="tabular-nums">
                {t("progress.tokensPerSecond", { n: fmtNum(it.tokens_per_second) })}
              </span>
            )}
          </div>
          {it.state === "writing" && (it.usual_remaining_seconds != null || it.longer_than_usual) && (
            <div className="mt-1 text-muted">
              {it.longer_than_usual
                ? t("progress.longer")
                : t("progress.usually", { duration: fmtDuration(it.usual_remaining_seconds ?? 0) })}
              {it.max_remaining_seconds != null && (
                <> · {t("progress.atMost", { duration: fmtDuration(it.max_remaining_seconds) })}</>
              )}
            </div>
          )}
        </li>
      ))}
      {more > 0 && (
        <li className="px-1 text-xs text-muted">{t("progress.andMore", { n: more })}</li>
      )}
    </ul>
  );
}

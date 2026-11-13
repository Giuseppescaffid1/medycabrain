import { useTranslation } from "react-i18next";
import type { BatchData } from "../../api/progress";
import { whenLabel } from "./format";

/**
 * Work handed over in bulk: no bar, because nothing moves until the answer
 * comes back (within 24 h). A bar that crept forward would be a lie; what is
 * true is when it was delivered and when the answer is due.
 */
export function BatchBlock({ batches }: { batches: BatchData[] }) {
  const { t } = useTranslation();
  return (
    <section>
      <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
        {t("progress.batches")}
      </h2>
      <p className="mb-3 text-xs text-muted/80">{t("progress.batchesHint")}</p>
      {batches.length === 0 ? (
        <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted shadow-card">
          {t("progress.batchesEmpty")}
        </p>
      ) : (
        <ul className="space-y-2">
          {batches.map((b) => (
            <li key={b.id} className="rounded-xl border border-border bg-surface p-4 text-sm shadow-card">
              <p className="break-words font-semibold text-navy">
                {t("progress.batchLine", {
                  n: b.items,
                  kind: b.kind_label,
                  when: whenLabel(b.submitted_at),
                  by: whenLabel(b.expected_by),
                })}
              </p>
              {b.model && <p className="mt-1 truncate text-xs text-muted">{b.model}</p>}
              {b.counts && b.counts.written != null && (
                <p className="mt-1 text-xs text-muted">
                  {t("progress.batchReturn", { written: b.counts.written, failed: b.counts.failed ?? 0 })}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import type { GraphNode, GraphPayload } from "../../api/graph";
import { Badge } from "../ui/primitives";
import { EASE } from "../ui/motion";

/**
 * Where a node sits and what hangs off it — the lineage the client navigates
 * the map for. Built with the app's own components rather than the CSS that
 * used to live inside the graph iframe, so it matches the rest of the
 * platform and behaves on a phone.
 */
export function NodePanel({
  node,
  data,
  onClose,
  onSelect,
}: {
  node: GraphNode | null;
  data: GraphPayload;
  onClose: () => void;
  onSelect: (n: GraphNode) => void;
}) {
  const { t } = useTranslation();
  const byId = Object.fromEntries(data.nodes.map((n) => [n.id, n]));

  const parent = node?.parent ? byId[node.parent] : undefined;
  const children = node ? data.nodes.filter((n) => n.parent === node.id) : [];
  const related = node
    ? data.edges
        .filter((e) => e.source === node.id || e.target === node.id)
        .map((e) => byId[e.source === node.id ? e.target : e.source])
        .filter((n): n is GraphNode => !!n && n.id !== node.parent)
        .filter((n) => !children.some((c) => c.id === n.id))
    : [];

  const ownerLabel =
    node?.owner === "competitor"
      ? t("scope.competitor")
      : node?.owner === "opportunity"
        ? t("map.legendOpportunity")
        : t("scope.medyca");
  const ownerClass =
    node?.owner === "competitor"
      ? "bg-warning/10 text-warning"
      : node?.owner === "opportunity"
        ? "bg-danger/10 text-danger"
        : "bg-secondary/10 text-secondary";

  return (
    <AnimatePresence>
      {node && (
        <motion.aside
          initial={{ x: "100%", opacity: 0.6 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: "100%", opacity: 0.6 }}
          transition={{ duration: 0.3, ease: EASE }}
          className="absolute inset-y-0 right-0 z-20 flex w-full max-w-sm flex-col overflow-y-auto border-l border-border bg-white shadow-float"
        >
          <div className="flex items-start justify-between gap-3 border-b border-border p-4">
            <div className="min-w-0">
              <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                <Badge className={ownerClass}>{ownerLabel}</Badge>
                <Badge className="bg-surface text-muted">{t(`map.kind.${node.group}`)}</Badge>
              </div>
              <h2 className="text-base font-bold text-heading">{node.label}</h2>
              {node.sub && <p className="mt-0.5 text-xs text-muted">{node.sub}</p>}
            </div>
            <button
              onClick={onClose}
              aria-label={t("common.close")}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted transition hover:bg-surface hover:text-navy"
            >
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
                <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          <div className="flex flex-col gap-5 p-4">
            {node.detail && <p className="text-sm text-navy">{node.detail}</p>}

            {node.url && (
              <a
                href={node.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex w-fit items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 text-xs font-bold text-secondary transition hover:border-secondary"
              >
                ↗ {t("map.openSource")}
              </a>
            )}

            {parent && (
              <Section title={t("map.partOf")}>
                <Chip node={parent} onSelect={onSelect} />
              </Section>
            )}

            {children.length > 0 && (
              <Section title={`${t("map.contains")} · ${children.length}`}>
                {children.map((c) => (
                  <Chip key={c.id} node={c} onSelect={onSelect} />
                ))}
              </Section>
            )}

            {related.length > 0 && (
              <Section title={t("map.connected")}>
                {related.map((r) => (
                  <Chip key={r.id} node={r} onSelect={onSelect} />
                ))}
              </Section>
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted">
        {title}
      </h3>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

function Chip({ node, onSelect }: { node: GraphNode; onSelect: (n: GraphNode) => void }) {
  const comp = node.owner === "competitor";
  return (
    <button
      onClick={() => onSelect(node)}
      className={
        "max-w-full truncate rounded-full border px-3 py-1.5 text-xs font-semibold transition " +
        (comp
          ? "border-warning/40 bg-warning/5 text-warning hover:border-warning"
          : "border-border bg-white text-navy hover:border-secondary")
      }
    >
      {node.label}
    </button>
  );
}

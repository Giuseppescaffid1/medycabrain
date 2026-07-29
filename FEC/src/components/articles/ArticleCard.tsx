import { useTranslation } from "react-i18next";
import type { KnowledgeDoc } from "../../api/knowledge";
import { Badge } from "../ui/primitives";
import { formatDate } from "../../lib/utils";

/**
 * A blog article in the library grid.
 *
 * Text-first, deliberately: an article has no 9:16 frame and no view count,
 * so dressing it as a reel would just be an empty thumbnail. What identifies
 * it at a glance is title, source and subject.
 */
export function ArticleCard({
  doc,
  onClick,
}: {
  doc: KnowledgeDoc;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  const comp = doc.owner_type === "competitor";

  return (
    <button
      onClick={onClick}
      className="group flex h-full w-full flex-col gap-2 rounded-xl border border-border bg-white p-4 text-left shadow-card transition duration-200 hover:border-secondary hover:shadow-float"
    >
      <div className="flex items-center gap-2">
        <span aria-hidden>📄</span>
        <Badge
          className={comp ? "bg-warning/10 text-warning" : "bg-secondary/10 text-secondary"}
        >
          {doc.source?.name || (comp ? t("scope.competitor") : "Medyca")}
        </Badge>
        {doc.language && doc.language !== "it" && (
          <Badge className="bg-surface text-muted uppercase">{doc.language}</Badge>
        )}
      </div>

      <h3 className="line-clamp-2 text-sm font-bold leading-snug text-navy group-hover:text-heading">
        {doc.title.replace(/ [—-] .*$/, "") || t("kb.untitled")}
      </h3>

      {doc.primary_topic && (
        <div className="text-xs font-semibold text-secondary">{doc.primary_topic}</div>
      )}

      <p className="line-clamp-3 flex-1 text-xs leading-relaxed text-muted">
        {doc.summary_it || t("articles.notEnriched")}
      </p>

      <div className="flex items-center justify-between text-[11px] text-muted/80">
        <span>{doc.published_at ? formatDate(doc.published_at) : ""}</span>
        {doc.author && <span className="truncate pl-2">{doc.author}</span>}
      </div>
    </button>
  );
}

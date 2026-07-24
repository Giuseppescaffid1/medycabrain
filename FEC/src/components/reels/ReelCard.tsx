import { useTranslation } from "react-i18next";
import type { ReelListItem } from "../../api/types";
import { Badge } from "../ui/primitives";
import { cn, formatCount, formatLabel, mediaUrl } from "../../lib/utils";

export function ReelCard({
  reel,
  onClick,
}: {
  reel: ReelListItem;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  const thumb = mediaUrl(reel.thumbnail_file) || reel.thumbnail_url || null;

  return (
    <button
      onClick={onClick}
      className="group flex h-full w-full flex-col overflow-hidden rounded-xl border border-border bg-white text-left shadow-card transition duration-200 hover:border-secondary hover:shadow-float"
    >
      <div className="relative aspect-[9/16] w-full overflow-hidden bg-surface">
        {thumb ? (
          <img
            src={thumb}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-3xl text-border">
            🎬
          </div>
        )}
        {reel.is_favorite && (
          <span className="absolute right-2 top-2 text-lg drop-shadow">⭐</span>
        )}
        {reel.is_inspiration && (
          <span className="absolute right-2 top-9 text-lg drop-shadow">💡</span>
        )}
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-2">
          <div className="flex items-center gap-2 text-xs text-white">
            <span>▶ {formatCount(reel.view_count)}</span>
            <span>♥ {formatCount(reel.like_count)}</span>
          </div>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-xs font-semibold text-secondary">
            @{reel.account_username}
          </span>
          {reel.content_format && (
            <Badge className="shrink-0">{formatLabel(reel.content_format)}</Badge>
          )}
        </div>
        <p className="line-clamp-3 text-xs text-muted">
          {reel.summary_it || reel.caption || "—"}
        </p>
        {reel.cluster_label && (
          <Badge className={cn("mt-auto self-start bg-surface text-heading")}>
            {reel.cluster_label}
          </Badge>
        )}
        {reel.transcribe_status !== "done" && (
          <span className="text-[10px] text-muted/80">
            {reel.enrich_status === "done"
              ? ""
              : reel.transcribe_status === "done"
                ? ""
                : "⏳ in elaborazione"}
          </span>
        )}
      </div>
    </button>
  );
}

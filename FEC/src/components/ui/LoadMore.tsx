import { useTranslation } from "react-i18next";
import { Button } from "./primitives";

/**
 * "n / total" and the button that fetches the next page. A list that stops at
 * its first page without saying so reads as "this is everything": the client
 * had 903 competitor articles and saw 100.
 */
export function LoadMore({
  shown,
  total,
  hasMore,
  loading,
  onMore,
}: {
  shown: number;
  total: number;
  hasMore: boolean;
  loading: boolean;
  onMore: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="mt-6 flex items-center justify-center gap-4">
      <span className="text-xs font-semibold text-muted">
        {shown} / {total}
      </span>
      {hasMore && (
        <Button variant="secondary" onClick={onMore} loading={loading}>
          {t("library.loadMore")}
        </Button>
      )}
    </div>
  );
}

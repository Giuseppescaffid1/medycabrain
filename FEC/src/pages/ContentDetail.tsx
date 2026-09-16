import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ReelDetailDrawer } from "../components/reels/ReelDetailDrawer";
import { ArticleDetailDrawer } from "../components/articles/ArticleDetailDrawer";
import { fetchReel } from "../api/endpoints";
import { fetchKnowledgeDoc } from "../api/knowledge";
import { Button, EmptyState, Spinner } from "../components/ui/primitives";
import { PageTransition } from "../components/ui/motion";

/**
 * The address a reference resolves to: `/content/:kind/:id`. Reached by the
 * "vai al contenuto" field and usable as a shareable link, it opens the same
 * detail drawer the Library already uses — no new card was designed.
 *
 * The detail endpoints answer by id alone, blind to scope, so this works for a
 * Medyca or a competitor item without knowing which side it belongs to. The one
 * piece of logic here is telling "still loading" apart from "gone": the MCP
 * cites only active content, but an old reference can point at an id that was
 * since removed, and the drawer alone would spin forever on that 404. So we
 * resolve the content first and only mount the drawer once it is in cache; a
 * failure shows a plain "not found" instead of an endless spinner.
 */
export default function ContentDetail() {
  const { t } = useTranslation();
  const { kind, id } = useParams();
  const navigate = useNavigate();

  const numId = Number(id);
  const valid = (kind === "reel" || kind === "blog") && Number.isInteger(numId) && numId > 0;

  // Return to where the reference was clicked; on a cold deep-link there is no
  // history to go back to, so land on the chat where the field lives.
  const goBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate("/knowledge-bank");
  };

  // The data shape does not matter here — this page only needs to know whether
  // the id resolves — so the result is typed as unknown and left to the drawer.
  const query = useQuery<unknown, Error>({
    // Same keys the drawers use, so mounting one below reads from cache instead
    // of firing a second request.
    queryKey: kind === "reel" ? ["reel", numId] : ["knowledge-doc", numId],
    queryFn: () => (kind === "reel" ? fetchReel(numId) : fetchKnowledgeDoc(numId)),
    enabled: valid,
    // A removed id should surface the "not found" state at once, not after three
    // retries.
    retry: false,
  });

  if (!valid || query.isError) {
    return (
      <PageTransition>
        <div className="flex h-full flex-col items-center justify-center px-4">
          <EmptyState message={t("content.notFound")} />
          <Button onClick={goBack}>{t("content.backToLibrary")}</Button>
        </div>
      </PageTransition>
    );
  }

  if (query.isLoading) {
    return (
      <PageTransition>
        <Spinner label={t("common.loading")} />
      </PageTransition>
    );
  }

  return kind === "reel" ? (
    <ReelDetailDrawer reelId={numId} onClose={goBack} />
  ) : (
    <ArticleDetailDrawer docId={numId} onClose={goBack} />
  );
}

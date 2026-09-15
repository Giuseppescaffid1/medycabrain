import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  deleteUpload,
  importLinks,
  listUploads,
  uploadInterview,
  type Upload,
} from "../../api/uploads";
import { Badge, Button, Skeleton, fieldCls } from "../ui/primitives";
import {
  FilterSelect,
  FormError,
  PanelEmpty,
  PanelHeader,
  ResultCount,
  RowAction,
  RowActions,
  SearchField,
  TableFrame,
  Th,
  Toolbar,
} from "../manage/parts";
import { formatDate } from "../../lib/utils";

/**
 * Upload an interview (audio/video) → transcript → article + draft.
 *
 * The doctor's past interviews already say everything for a blog article;
 * this is the door. The upload bytes are what the user waits on (a real
 * progress bar); the transcription that follows is a background job, so the
 * list polls for status while it works.
 *
 * Two doors, one list: a FILE the client drags in, or a LINK he pastes. The
 * second exists because his reference material lives on YouTube and on Vimeo
 * (the TVRS episodes) and he sends it as a messy block of notes — so the
 * paste box takes the block whole and the backend pulls the videos out of it,
 * whichever of the two hosts they are on.
 *
 * Two controls travel with a pasted batch, and they are deliberately separate
 * questions: "is this reference material" (why it is here) and "is it Medyca's
 * own" (whose it is, which decides whether it counts as their coverage).
 *
 * The drop zone stays visible here (it IS the primary action, there is no
 * separate "add" form to fold away), with the list of past uploads below it.
 */
export function UploadPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [links, setLinks] = useState("");
  const [inspiration, setInspiration] = useState(true);
  const [owner, setOwner] = useState<Upload["owner_type"]>("competitor");
  const [linkNote, setLinkNote] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["uploads"],
    queryFn: listUploads,
    // While anything is still transcribing, keep the statuses moving.
    refetchInterval: (q) =>
      (q.state.data ?? []).some((u: Upload) => u.transcribe_status === "pending")
        ? 4000
        : false,
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["uploads"] });

  const upload = useMutation({
    mutationFn: (file: File) => uploadInterview(file, title, setPct),
    onSuccess: () => {
      setPct(null);
      setTitle("");
      setError("");
      invalidate();
    },
    onError: (e: unknown) => {
      setPct(null);
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || t("common.error"));
    },
  });
  const remove = useMutation({ mutationFn: deleteUpload, onSuccess: invalidate });

  const addLinks = useMutation({
    mutationFn: () => importLinks(links, owner, inspiration),
    onSuccess: (res) => {
      setLinks("");
      setError("");
      // Say what actually happened to each link. "Added 4" while silently
      // dropping 3 duplicates is how a client concludes the feature is broken.
      const parts = [t("uploads.linksAdded", { count: res.creati.length })];
      if (res.gia_presenti.length)
        parts.push(t("uploads.linksDuplicate", { count: res.gia_presenti.length }));
      if (res.rifiutati.length)
        parts.push(t("uploads.linksRefused", { count: res.rifiutati.length }));
      setLinkNote(parts.join(" · "));
      invalidate();
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || t("common.error"));
    },
  });

  const pick = (files: FileList | null) => {
    const f = files?.[0];
    if (f) upload.mutate(f);
  };

  const statusBadge = (u: Upload) => {
    if (u.transcribe_status === "pending")
      return <Badge className="bg-secondary/10 text-secondary">{t("uploads.working")}</Badge>;
    if (u.transcribe_status === "failed")
      return (
        <span title={u.last_error}>
          <Badge className="bg-danger/10 text-danger">{t("uploads.failed")}</Badge>
        </span>
      );
    return <Badge className="bg-success/10 text-success">{t("uploads.ready")}</Badge>;
  };

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter((u) => {
      if (status !== "all" && u.transcribe_status !== status) return false;
      if (!needle) return true;
      return (
        (u.title ?? "").toLowerCase().includes(needle) ||
        (u.original_name ?? "").toLowerCase().includes(needle)
      );
    });
  }, [data, q, status]);

  return (
    <section aria-labelledby="tab-uploads" id="panel-uploads" role="tabpanel">
      <PanelHeader description={t("uploads.subtitle")} />

      <div className="mb-6 rounded-xl border border-border bg-surface p-4 shadow-card">
        <label className="mb-3 flex flex-col gap-1">
          <span className="text-xs font-bold uppercase tracking-wider text-muted">
            {t("uploads.titleLabel")}
          </span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t("uploads.titlePlaceholder")}
            className={fieldCls + " w-full max-w-md"}
          />
        </label>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pick(e.dataTransfer.files);
          }}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          className={
            "flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed bg-white p-8 text-center transition duration-200 " +
            "outline-none focus-visible:ring-2 focus-visible:ring-secondary " +
            (dragging ? "border-secondary bg-secondary/5" : "border-border hover:border-secondary/50")
          }
        >
          <span className="text-2xl" aria-hidden>🎙️</span>
          <span className="text-sm font-semibold text-navy">{t("uploads.drop")}</span>
          <span className="text-xs text-muted">{t("uploads.formats")}</span>
          <input
            ref={inputRef}
            type="file"
            accept="audio/*,video/*"
            className="hidden"
            onChange={(e) => pick(e.target.files)}
          />
        </div>

        {upload.isPending && pct !== null && (
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-xs text-muted">
              <span>{t("uploads.uploading")}</span>
              <span className="tabular-nums">{pct}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-white">
              <div
                className="h-full rounded-full bg-secondary transition-all duration-200"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}
        {error && <FormError message={error} />}

        <div className="mt-6 border-t border-border pt-4">
          <label className="mb-2 flex flex-col gap-1" htmlFor="video-links">
            <span className="text-xs font-bold uppercase tracking-wider text-muted">
              {t("uploads.linksLabel")}
            </span>
            <span className="text-xs text-muted">{t("uploads.linksHint")}</span>
          </label>
          <textarea
            id="video-links"
            value={links}
            onChange={(e) => setLinks(e.target.value)}
            rows={4}
            placeholder={t("uploads.linksPlaceholder")}
            className={
              "w-full rounded-xl border border-border bg-white p-3 text-sm text-navy " +
              "placeholder:text-muted/70 outline-none transition duration-200 " +
              "focus:border-secondary"
            }
          />
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-navy">
              <input
                type="checkbox"
                checked={inspiration}
                onChange={(e) => setInspiration(e.target.checked)}
                className="h-4 w-4 rounded border-border text-secondary focus-visible:ring-2 focus-visible:ring-secondary"
              />
              {t("uploads.inspirationLabel")}
            </label>
            <label className="flex items-center gap-2 text-sm text-navy">
              <span className="text-muted">{t("uploads.ownerLabel")}</span>
              <select
                value={owner}
                onChange={(e) => setOwner(e.target.value as Upload["owner_type"])}
                className={fieldCls + " w-40"}
              >
                <option value="competitor">{t("uploads.ownerExternal")}</option>
                <option value="owned">{t("uploads.ownerMedyca")}</option>
              </select>
            </label>
            <Button
              variant="secondary"
              onClick={() => addLinks.mutate()}
              disabled={!links.trim()}
              loading={addLinks.isPending}
            >
              {t("uploads.linksAdd")}
            </Button>
          </div>
          {/* Saying it here, next to the control: marking someone else's video
              as Medyca's makes the gap engine treat that subject as covered. */}
          {owner === "owned" && (
            <p className="mt-2 text-xs text-warning">{t("uploads.ownerWarning")}</p>
          )}
          {linkNote && <p className="mt-2 text-xs text-muted">{linkNote}</p>}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-24" />
      ) : !data?.length ? (
        <PanelEmpty message={t("uploads.empty")} />
      ) : (
        <>
          <Toolbar>
            <SearchField value={q} onChange={setQ} placeholder={t("manage.searchUploads")} />
            <FilterSelect
              value={status}
              onChange={setStatus}
              label={t("manage.filterLabel")}
              options={[
                { value: "all", label: t("manage.filterAll") },
                { value: "pending", label: t("uploads.working") },
                { value: "done", label: t("uploads.ready") },
                { value: "failed", label: t("uploads.failed") },
              ]}
            />
            <ResultCount shown={rows.length} total={data.length} />
          </Toolbar>

          {!rows.length ? (
            <PanelEmpty message={t("manage.noResults")} />
          ) : (
            <TableFrame
              minWidth={600}
              head={
                <>
                  <Th>{t("uploads.file")}</Th>
                  <Th>{t("accounts.status")}</Th>
                  <Th>{t("uploads.result")}</Th>
                  <Th align="right" />
                </>
              }
            >
              {rows.map((u) => (
                <tr key={u.id} className="text-navy">
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{u.title || u.original_name}</span>
                      {u.is_inspiration && (
                        <Badge className="bg-secondary/10 text-secondary">
                          {t("uploads.inspirationBadge")}
                        </Badge>
                      )}
                      {u.owner_type === "owned" && (
                        <Badge className="bg-success/10 text-success">
                          {t("uploads.ownerMedyca")}
                        </Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted">
                      {u.kind === "video" ? "🎬" : "🔊"} {formatDate(u.created_at)}
                      {u.channel && <> · {u.channel}</>}
                    </div>
                    {u.source_url && (
                      <a
                        href={u.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-secondary underline underline-offset-2 hover:text-heading"
                      >
                        {t("uploads.openSource")}
                      </a>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {statusBadge(u)}
                    {/* A blocked download has a remedy, and the client can only
                        act on it if he can read it — a tooltip is not reading. */}
                    {u.transcribe_status === "failed" && u.last_error && (
                      <p className="mt-1 max-w-xs text-xs text-danger">{u.last_error}</p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {u.transcribe_status === "done" ? (
                      <div className="flex flex-col gap-1">
                        {u.document && (
                          <Link
                            to="/medyca/library?type=article"
                            className="font-semibold text-secondary hover:text-heading"
                          >
                            {t("uploads.seeArticle")}
                          </Link>
                        )}
                        {u.blog_draft && (
                          <Link
                            to="/second-brain"
                            className="font-semibold text-secondary hover:text-heading"
                          >
                            {t("uploads.seeDraft")}
                          </Link>
                        )}
                      </div>
                    ) : u.document ? (
                      <Link
                        to="/medyca/library?type=article"
                        className="font-semibold text-secondary hover:text-heading"
                      >
                        {t("uploads.seeReference")}
                      </Link>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <RowActions>
                      <RowAction
                        tone="danger"
                        onClick={() => {
                          if (confirm(t("uploads.confirmRemove"))) remove.mutate(u.id);
                        }}
                      >
                        {t("accounts.remove")}
                      </RowAction>
                    </RowActions>
                  </td>
                </tr>
              ))}
            </TableFrame>
          )}
        </>
      )}
    </section>
  );
}

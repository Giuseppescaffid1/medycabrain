import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  AUDIO_EXTENSIONS,
  MAX_UPLOAD_BYTES,
  UPLOAD_ACCEPT,
  VIDEO_EXTENSIONS,
  deleteUpload,
  importLinks,
  listUploads,
  retryUpload,
  uploadInterview,
  type LinkImport,
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
 * Every pasted link gets an answer: the outcome box under the paste field lists
 * what was added, restarted, already there, or not readable — each with its
 * address and, when refused, the reason. A count alone ("non leggibili: 3")
 * leaves the client guessing which ones, and he complained exactly that.
 * Files go up one at a time (a queue), and every error is mapped to a sentence
 * he can act on rather than one generic "errore".
 *
 * The drop zone stays visible here (it IS the primary action, there is no
 * separate "add" form to fold away), with the list of past uploads below it.
 */
/** An address cut short for a list: the host and the start of the path. */
function shortUrl(url: string) {
  const bare = url.replace(/^https?:\/\/(www\.)?/, "");
  return bare.length > 60 ? bare.slice(0, 57) + "…" : bare;
}

const ALLOWED_EXT = new Set([...AUDIO_EXTENSIONS, ...VIDEO_EXTENSIONS]);

export function UploadPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [fileErrors, setFileErrors] = useState<string[]>([]);
  const [fileNote, setFileNote] = useState("");
  const [queue, setQueue] = useState<{ current: number; total: number } | null>(null);
  const busy = queue !== null;
  const [dragging, setDragging] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [links, setLinks] = useState("");
  const [inspiration, setInspiration] = useState(true);
  const [owner, setOwner] = useState<Upload["owner_type"]>("competitor");
  // Link errors and outcome live under the textarea, apart from the file's:
  // an error shown under the wrong control is read as being about that one.
  const [linkError, setLinkError] = useState("");
  const [outcome, setOutcome] = useState<LinkImport | null>(null);

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

  /** The sentence for a failed request. Each status has a different remedy,
   *  so they are told apart instead of falling on one generic error. */
  const reasonFor = (e: unknown): string => {
    const err = e as { response?: { status?: number; data?: { detail?: string } } };
    const status = err?.response?.status;
    if (!err?.response) return t("uploads.errNetwork");
    if (status === 413) return t("uploads.errTooBig");
    if (status === 502 || status === 503 || status === 504) return t("uploads.errTimeout");
    return err.response.data?.detail || t("common.error");
  };

  const remove = useMutation({ mutationFn: deleteUpload, onSuccess: invalidate });
  const retry = useMutation({
    mutationFn: retryUpload,
    onSuccess: invalidate,
    onError: (e: unknown) => setLinkError(reasonFor(e)),
  });

  const addLinks = useMutation({
    mutationFn: () => importLinks(links, owner, inspiration),
    onSuccess: (res) => {
      setLinks("");
      setLinkError("");
      setOutcome(res);
      invalidate();
    },
    onError: (e: unknown) => {
      setOutcome(null);
      setLinkError(reasonFor(e));
    },
  });

  /** Files go up one after the other: parallel uploads share one connection
   *  and one nginx limit, and a failure of the second must not hide the first. */
  const uploadAll = async (files: File[]) => {
    if (busy || !files.length) return;
    const errors: string[] = [];
    let ok = 0;
    setFileErrors([]);
    setFileNote("");
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      const ext = f.name.includes(".") ? f.name.split(".").pop()!.toLowerCase() : "";
      if (!ALLOWED_EXT.has(ext)) {
        errors.push(t("uploads.fileBadType", { name: f.name }));
        continue;
      }
      if (f.size > MAX_UPLOAD_BYTES) {
        errors.push(t("uploads.fileTooBig", { name: f.name }));
        continue;
      }
      setQueue({ current: i + 1, total: files.length });
      setPct(0);
      try {
        // One title can only describe one file.
        await uploadInterview(f, files.length === 1 ? title : "", setPct);
        ok++;
        invalidate();
      } catch (e) {
        errors.push(t("uploads.errNamed", { name: f.name, reason: reasonFor(e) }));
      }
    }
    setQueue(null);
    setPct(null);
    if (ok) {
      setTitle("");
      setFileNote(t("uploads.uploadedCount", { count: ok }));
    }
    setFileErrors(errors);
  };

  const pick = (files: FileList | null) => {
    void uploadAll(Array.from(files ?? []));
    // Without this the same file cannot be chosen again after an error: the
    // input sees no change and fires nothing.
    if (inputRef.current) inputRef.current.value = "";
  };

  const statusBadge = (u: Upload) => {
    if (u.transcribe_status === "pending")
      return <Badge className="bg-secondary/10 text-secondary">{t("uploads.working")}</Badge>;
    if (u.transcribe_status === "skipped")
      return <Badge className="bg-warning/10 text-warning">{t("uploads.withoutTranscript")}</Badge>;
    if (u.transcribe_status === "batched")
      return <Badge className="bg-secondary/10 text-secondary">{t("uploads.analysing")}</Badge>;
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
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (!busy) pick(e.dataTransfer.files);
          }}
          onClick={() => !busy && inputRef.current?.click()}
          role="button"
          tabIndex={busy ? -1 : 0}
          aria-disabled={busy}
          onKeyDown={(e) =>
            !busy && (e.key === "Enter" || e.key === " ") && inputRef.current?.click()
          }
          className={
            "flex flex-col items-center gap-2 rounded-xl border-2 border-dashed bg-white p-8 text-center transition duration-200 " +
            "outline-none focus-visible:ring-2 focus-visible:ring-secondary " +
            (busy
              ? "cursor-not-allowed opacity-60 border-border"
              : "cursor-pointer " +
                (dragging ? "border-secondary bg-secondary/5" : "border-border hover:border-secondary/50"))
          }
        >
          <span className="text-2xl" aria-hidden>🎙️</span>
          <span className="text-sm font-semibold text-navy">
            {busy ? t("uploads.dropBusy") : t("uploads.drop")}
          </span>
          <span className="text-xs text-muted">{t("uploads.formats")}</span>
          <input
            ref={inputRef}
            type="file"
            accept={UPLOAD_ACCEPT}
            multiple
            disabled={busy}
            className="hidden"
            onChange={(e) => pick(e.target.files)}
          />
        </div>

        {busy && pct !== null && (
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-xs text-muted">
              <span>
                {t("uploads.uploading")}
                {queue && queue.total > 1 && (
                  <> · {t("uploads.queueProgress", { current: queue.current, total: queue.total })}</>
                )}
              </span>
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
        {fileNote && !fileErrors.length && (
          <p role="status" className="mt-3 text-sm text-success">{fileNote}</p>
        )}
        {fileErrors.map((m, i) => (
          <FormError key={i} message={m} />
        ))}

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
            onChange={(e) => {
              setLinks(e.target.value);
              // A new edit means the old verdict is about a different text.
              setOutcome(null);
              setLinkError("");
            }}
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
              onClick={() => {
                setOutcome(null);
                setLinkError("");
                addLinks.mutate();
              }}
              disabled={!links.trim() || addLinks.isPending}
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
          {linkError && <FormError message={linkError} />}
          {outcome && <LinkOutcome outcome={outcome} onClose={() => setOutcome(null)} />}
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
                      {u.kind === "video" ? "🎬" : u.kind === "article" ? "📄" : "🔊"} {formatDate(u.created_at)}
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
                    {u.transcribe_status === "pending" && u.job_progress != null && (
                      <div className="mt-2 max-w-xs">
                        <div
                          className="h-1.5 w-full overflow-hidden rounded-full bg-white"
                          role="progressbar"
                          aria-valuenow={u.job_progress}
                          aria-valuemin={0}
                          aria-valuemax={100}
                        >
                          <div
                            className="h-full rounded-full bg-secondary transition-all duration-200 motion-reduce:transition-none"
                            style={{ width: `${u.job_progress}%` }}
                          />
                        </div>
                        {u.job_message && (
                          <p className="mt-1 text-xs text-muted">{u.job_message}</p>
                        )}
                      </div>
                    )}
                    {/* A deferred analysis is a note on a finished row, not a failure. */}
                    {u.transcribe_status !== "failed" && u.last_error && (
                      <p className="mt-1 max-w-xs text-xs text-muted">{u.last_error}</p>
                    )}
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
                            to={`/content/blog/${u.document}`}
                            state={{ fromApp: true }}
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
                        to={`/content/blog/${u.document}`}
                        state={{ fromApp: true }}
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
                      {u.transcribe_status === "failed" && (
                        <RowAction
                          tone="action"
                          disabled={retry.isPending}
                          onClick={() => {
                            setLinkError("");
                            retry.mutate(u.id);
                          }}
                        >
                          {t("uploads.retry")}
                        </RowAction>
                      )}
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

/** The per-link verdict of a paste, grouped, with the reason where there is
 *  one. Closable, and replaced on the next paste. */
function LinkOutcome({ outcome, onClose }: { outcome: LinkImport; onClose: () => void }) {
  const { t } = useTranslation();
  const bad = [...outcome.non_riconosciuti, ...outcome.rifiutati];
  const nothing =
    !outcome.creati.length && !outcome.riprovati.length && !outcome.gia_presenti.length && !bad.length;
  return (
    <div
      role="status"
      className="mt-3 rounded-xl border border-border bg-white p-3 text-sm text-navy"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="font-semibold">{t("uploads.linksOutcomeTitle")}</span>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full px-2 py-0.5 text-xs text-secondary hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary"
        >
          {t("uploads.linksOutcomeClose")}
        </button>
      </div>
      {nothing && <p className="text-xs text-muted">{t("uploads.linksNone")}</p>}
      <OutcomeGroup
        title={t("uploads.linksOutcomeAdded", { count: outcome.creati.length })}
        items={outcome.creati.map((c) => ({ url: c.source_url }))}
        tone="text-success"
      />
      <OutcomeGroup
        title={t("uploads.linksOutcomeRetried", { count: outcome.riprovati.length })}
        items={outcome.riprovati.map((url) => ({ url }))}
        tone="text-secondary"
      />
      <OutcomeGroup
        title={t("uploads.linksOutcomeDuplicate", { count: outcome.gia_presenti.length })}
        items={outcome.gia_presenti.map((url) => ({ url }))}
        tone="text-muted"
      />
      <OutcomeGroup
        title={t("uploads.linksOutcomeUnknown", { count: bad.length })}
        items={bad.map((b) => ({ url: b.url, reason: b.motivo }))}
        tone="text-danger"
      />
    </div>
  );
}

function OutcomeGroup({
  title,
  items,
  tone,
}: {
  title: string;
  items: { url: string; reason?: string }[];
  tone: string;
}) {
  if (!items.length) return null;
  return (
    <div className="mt-2">
      <p className={"text-xs font-bold " + tone}>{title}</p>
      <ul className="mt-1 flex flex-col gap-1">
        {items.map((it) => (
          <li key={it.url} className="text-xs">
            <a
              href={it.url}
              target="_blank"
              rel="noreferrer"
              className="break-all text-secondary underline underline-offset-2 hover:text-heading"
            >
              {shortUrl(it.url)}
            </a>
            {it.reason && <span className="block text-muted">{it.reason}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

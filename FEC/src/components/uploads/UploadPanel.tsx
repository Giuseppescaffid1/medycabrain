import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  deleteUpload,
  listUploads,
  uploadInterview,
  type Upload,
} from "../../api/uploads";
import { Badge, Button, Skeleton, fieldCls } from "../ui/primitives";
import { formatDate } from "../../lib/utils";

/**
 * Upload an interview (audio/video) → transcript → article + draft.
 *
 * The doctor's past interviews already say everything for a blog article;
 * this is the door. The upload bytes are what the user waits on (a real
 * progress bar); the transcription that follows is a background job, so the
 * list polls for status while it works.
 */
export function UploadPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);

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

  return (
    <section>
      <h2 className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">
        {t("uploads.title")}
      </h2>
      <p className="mb-4 text-sm text-muted">{t("uploads.subtitle")}</p>

      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t("uploads.titlePlaceholder")}
        className={fieldCls + " mb-2 w-full max-w-md"}
      />

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
          "flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition duration-200 " +
          (dragging
            ? "border-secondary bg-secondary/5"
            : "border-border bg-surface hover:border-secondary/50")
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
          <div className="h-2 w-full overflow-hidden rounded-full bg-surface">
            <div
              className="h-full rounded-full bg-secondary transition-all duration-200"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}
      {error && <p className="mt-3 text-sm font-semibold text-danger">⚠ {error}</p>}

      {isLoading ? (
        <Skeleton className="mt-4 h-24" />
      ) : data && data.length > 0 ? (
        <div className="mt-4 overflow-x-auto rounded-xl border border-border bg-white shadow-card">
          <table className="w-full min-w-[600px] text-sm">
            <thead className="bg-surface text-left text-xs font-bold uppercase tracking-wider text-muted">
              <tr>
                <th className="px-4 py-3">{t("uploads.file")}</th>
                <th className="px-4 py-3">{t("accounts.status")}</th>
                <th className="px-4 py-3">{t("uploads.result")}</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.map((u) => (
                <tr key={u.id} className="text-navy">
                  <td className="px-4 py-3">
                    <div className="font-semibold">
                      {u.title || u.original_name}
                    </div>
                    <div className="text-xs text-muted">
                      {u.kind === "video" ? "🎬" : "🔊"} {formatDate(u.created_at)}
                    </div>
                  </td>
                  <td className="px-4 py-3">{statusBadge(u)}</td>
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
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => {
                        if (confirm(t("uploads.confirmRemove"))) remove.mutate(u.id);
                      }}
                      className="text-xs font-semibold text-muted hover:text-danger"
                    >
                      {t("accounts.remove")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

import { apiClient } from "./client";

/** Something the client brought in himself — a FILE or a LINK — and where it
 *  got to. `source_url` empty means it was an uploaded file. */
export interface Upload {
  id: number;
  kind: "audio" | "video" | "article";
  original_name: string;
  title: string;
  size_bytes: number;
  duration_s: number | null;
  transcribe_status: "pending" | "done" | "failed" | "skipped" | "batched";
  document: number | null;
  blog_draft: number | null;
  last_error: string;
  created_at: string;
  /** The public page a linked video came from. "" for an uploaded file. */
  source_url: string;
  /** Who published it, e.g. "YouTVRS". */
  channel: string;
  /** Whose content it is — decides whether it counts as Medyca's coverage. */
  owner_type: "owned" | "competitor";
  /** Why it is here: reference material the client added on purpose. */
  is_inspiration: boolean;
  /** Progress (0-100) and message of the live job; null/"" when none runs. */
  job_progress: number | null;
  job_message: string;
}

/** The file types the server accepts. Must match `_AUDIO_EXT`/`_VIDEO_EXT` in
 *  BEC/core/views.py (UploadedMediaViewSet) — one list per side, so the
 *  picker never offers what the server then refuses. */
export const AUDIO_EXTENSIONS = [
  "mp3", "m4a", "wav", "aac", "ogg", "flac", "opus", "amr", "wma", "aiff", "aif", "caf",
];
export const VIDEO_EXTENSIONS = ["mp4", "mov", "m4v", "webm", "mkv", "avi", "3gp"];
export const UPLOAD_ACCEPT = [...AUDIO_EXTENSIONS, ...VIDEO_EXTENSIONS]
  .map((e) => `.${e}`)
  .join(",");

/** Largest file the server takes: nginx `client_max_body_size 1G` on the
 *  /api/v1/uploads/ location (deploy config, medycabrain-port). Past it the
 *  client would upload for minutes and then get a bare 413. */
export const MAX_UPLOAD_BYTES = 1024 * 1024 * 1024;

export interface LinkImport {
  creati: Upload[];
  gia_presenti: string[];
  /** A failed/removed link pasted again: it restarted. */
  riprovati: string[];
  rifiutati: { url: string; motivo: string }[];
  /** Addresses found but not readable (Instagram, Drive, PDF…), with why. */
  non_riconosciuti: { url: string; motivo: string }[];
}

export async function listUploads(): Promise<Upload[]> {
  const { data } = await apiClient.get("/uploads/", { params: { page_size: 100 } });
  return Array.isArray(data) ? data : data.results;
}

/** Upload a file (multipart). Returns immediately: the transcription runs as
 *  a detached job, so the caller polls the upload list for status. */
export async function uploadInterview(
  file: File,
  title: string,
  onProgress?: (pct: number) => void
): Promise<Upload & { job_id: number }> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  const { data } = await apiClient.post("/uploads/", form, {
    headers: { "Content-Type": "multipart/form-data" },
    // The bytes going UP is the slow part the user watches; the transcription
    // that follows is a background job with its own status.
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100));
    },
  });
  return data;
}

/** Paste a blob of text; every video link in it becomes an item.
 *  The client pastes his notes, not a clean list — the backend pulls the
 *  videos out and collapses duplicate spellings of the same one. */
export async function importLinks(
  text: string,
  ownerType: Upload["owner_type"],
  isInspiration: boolean
): Promise<LinkImport> {
  const { data } = await apiClient.post("/uploads/from-links/", {
    text,
    owner_type: ownerType,
    is_inspiration: isInspiration,
  });
  return data;
}

export async function deleteUpload(id: number): Promise<void> {
  await apiClient.delete(`/uploads/${id}/`);
}

/** Put a failed item back in the queue (the client's explicit gesture). */
export async function retryUpload(id: number): Promise<void> {
  await apiClient.post(`/uploads/${id}/retry/`);
}

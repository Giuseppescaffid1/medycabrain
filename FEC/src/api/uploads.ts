import { apiClient } from "./client";

/** An interview the client uploaded, and where it got to. */
export interface Upload {
  id: number;
  kind: "audio" | "video";
  original_name: string;
  title: string;
  size_bytes: number;
  duration_s: number | null;
  transcribe_status: "pending" | "done" | "failed" | "skipped";
  document: number | null;
  blog_draft: number | null;
  last_error: string;
  created_at: string;
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

export async function deleteUpload(id: number): Promise<void> {
  await apiClient.delete(`/uploads/${id}/`);
}

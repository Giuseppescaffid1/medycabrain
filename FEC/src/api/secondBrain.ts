import { apiClient } from "./client";
import type { Job } from "./jobs";

export interface SourceRef {
  kind: string;
  title: string;
  url: string;
}

export interface ContentIdea {
  hook_it: string;
  content_format: string;
  scope: string;
  id: number;
  argument_it: string;
  rationale_it: string;
  angle_it: string;
  is_gap: boolean;
  source_refs: SourceRef[];
  status: "proposed" | "saved" | "dismissed";
  batch: string;
  created_at: string;
}

export async function fetchIdeas(status?: string): Promise<ContentIdea[]> {
  const { data } = await apiClient.get<ContentIdea[] | { results: ContentIdea[] }>(
    "/second-brain/ideas/",
    { params: { status } }
  );
  return Array.isArray(data) ? data : data.results;
}

export async function generateIdeas(n = 8): Promise<ContentIdea[]> {
  // Runs a local LLM over competitor vs Medyca coverage — can take a couple of minutes.
  const { data } = await apiClient.post<ContentIdea[]>(
    "/second-brain/ideas/generate/",
    { n },
    { timeout: 300000 }
  );
  return data;
}

export async function updateIdeaStatus(
  id: number,
  status: "saved" | "dismissed" | "proposed"
): Promise<ContentIdea> {
  const { data } = await apiClient.patch<ContentIdea>(`/second-brain/ideas/${id}/`, { status });
  return data;
}

// ── Cluster-driven blog drafts (Alberto's workflow) ──────────────────────
export interface BlogDraft {
  id: number;
  mode: "expand" | "draft";
  cluster_label: string;
  title: string;
  content_md: string;
  source_refs: SourceRef[];
  status: "proposed" | "saved" | "dismissed";
  created_at: string;
}

export async function fetchBlogDrafts(): Promise<BlogDraft[]> {
  const { data } = await apiClient.get<BlogDraft[] | { results: BlogDraft[] }>(
    "/second-brain/blog-drafts/"
  );
  return Array.isArray(data) ? data : data.results;
}

export async function updateBlogDraftStatus(
  id: number,
  status: "saved" | "dismissed" | "proposed"
): Promise<BlogDraft> {
  const { data } = await apiClient.patch<BlogDraft>(`/second-brain/blog-drafts/${id}/`, { status });
  return data;
}

/** Kick an editorial-plan job: n contents, optionally focused on one theme. */
export async function startPlanJob(n = 6, theme = ""): Promise<Job> {
  const { data } = await apiClient.post<Job>("/second-brain/ideas/plan/", { n, theme });
  return data;
}

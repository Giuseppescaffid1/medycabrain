import { apiClient } from "./client";

/** A blog we crawl — the TrackedAccount of the article world. */
export interface BlogSource {
  id: number;
  name: string;
  index_url: string;
  site_url: string;
  owner_type: "owned" | "competitor";
  language: string;
  is_active: boolean;
  notes: string;
  crawl_interval_h: number;
  strategy: string;
  last_crawled_at: string | null;
  consecutive_failures: number;
  last_error: string;
  document_count?: number;
  created_at: string;
}

export async function fetchBlogSources(): Promise<BlogSource[]> {
  const { data } = await apiClient.get("/blog-sources/", { params: { page_size: 100 } });
  return Array.isArray(data) ? data : data.results;
}

export async function addBlogSource(v: {
  name: string;
  index_url: string;
  owner_type: "owned" | "competitor";
}): Promise<BlogSource> {
  const { data } = await apiClient.post<BlogSource>("/blog-sources/", v);
  return data;
}

export async function updateBlogSource(
  id: number,
  patch: Partial<Pick<BlogSource, "is_active" | "name" | "crawl_interval_h" | "notes">>
): Promise<BlogSource> {
  const { data } = await apiClient.patch<BlogSource>(`/blog-sources/${id}/`, patch);
  return data;
}

export async function deleteBlogSource(id: number): Promise<void> {
  await apiClient.delete(`/blog-sources/${id}/`);
}

export async function crawlBlogSource(id: number): Promise<{ job_id: number }> {
  const { data } = await apiClient.post(`/blog-sources/${id}/crawl/`);
  return data;
}

export async function reactivateBlogSource(id: number): Promise<{ job_id: number }> {
  const { data } = await apiClient.post(`/blog-sources/${id}/reactivate/`);
  return data;
}

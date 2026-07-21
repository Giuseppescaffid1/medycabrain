import { apiClient } from "./client";

export interface Job {
  id: number;
  kind: "ideation" | "pipeline";
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  message: string;
  result: Record<string, unknown>;
  error: string;
  created_at: string;
  finished_at: string | null;
}

export async function listActiveJobs(): Promise<Job[]> {
  const { data } = await apiClient.get<Job[]>("/jobs/", { params: { active: 1 } });
  return data;
}

export async function getJob(id: number): Promise<Job> {
  const { data } = await apiClient.get<Job>(`/jobs/${id}/`);
  return data;
}

/** Kick off idea generation — returns immediately with a queued Job (202). */
export async function startIdeationJob(n = 8): Promise<Job> {
  const { data } = await apiClient.post<Job>("/second-brain/ideas/generate/", { n });
  return data;
}

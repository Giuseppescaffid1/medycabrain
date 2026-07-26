import { apiClient } from "./client";
import type { Job } from "./jobs";

export interface Source {
  title: string;
  url: string;
  kind?: string;
  weight?: number | null;
}
export interface StrategyBrief {
  brief_model?: string;
  draft_model?: string;
  id: number;
  input_text: string;
  source_kind: string;
  coverage: "covered" | "partial" | "gap";
  brief_md: string;
  draft_md: string;
  medyca_sources: Source[];
  competitor_sources: Source[];
  metrics: Record<string, number>;
  status: "proposed" | "saved" | "dismissed";
  created_at: string;
}
export interface CoverageMap {
  covered: { id: number | string; label: string; reels: number; docs: number; custom?: boolean }[];
  opportunities: { id: number | string; label: string; reels: number; similarity: number; custom?: boolean }[];
}

export async function analyzeInput(input_text: string, source_kind = "input"): Promise<Job> {
  const { data } = await apiClient.post<Job>("/second-brain/briefs/analyze/", {
    input_text,
    source_kind,
  });
  return data;
}

export async function generateDraft(briefId: number): Promise<Job> {
  const { data } = await apiClient.post<Job>(`/second-brain/briefs/${briefId}/draft/`, {});
  return data;
}

export async function fetchBriefs(): Promise<StrategyBrief[]> {
  const { data } = await apiClient.get<StrategyBrief[] | { results: StrategyBrief[] }>(
    "/second-brain/briefs/"
  );
  return Array.isArray(data) ? data : data.results;
}

export async function updateBriefStatus(
  id: number,
  status: "saved" | "dismissed" | "proposed"
): Promise<StrategyBrief> {
  const { data } = await apiClient.patch<StrategyBrief>(`/second-brain/briefs/${id}/`, { status });
  return data;
}

export async function fetchCoverageMap(): Promise<CoverageMap> {
  const { data } = await apiClient.get<CoverageMap>("/second-brain/coverage-map/");
  return data;
}

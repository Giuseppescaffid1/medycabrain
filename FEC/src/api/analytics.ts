import { apiClient } from "./client";
import type { Scope } from "./endpoints";

export interface Overview {
  scope: string;
  reels: number;
  avg_views: number;
  avg_likes: number;
  total_views: number;
  total_likes: number;
  top_theme: string | null;
}
export interface MonthPoint {
  month: string;
  reels: number;
  views: number;
  likes: number;
}
export interface TopContent {
  id: number;
  shortcode: string;
  account: string;
  title: string;
  views: number;
  likes: number;
  weight: number;
  url: string;
  thumbnail_file: string;
}
export interface ClusterPerf {
  id: number;
  label: string;
  reels: number;
  avg_weight: number;
  avg_views: number;
}
export interface Benchmark {
  medyca: { reels: number; avg_views: number; avg_likes: number };
  competitor: { reels: number; avg_views: number; avg_likes: number };
}

async function metric<T>(name: string, scope: Scope): Promise<T> {
  const { data } = await apiClient.get<T>("/analytics/", {
    params: { metric: name, scope },
  });
  return data;
}

export const fetchOverview = (s: Scope) => metric<Overview>("overview", s);
export const fetchEngagementOverTime = (s: Scope) => metric<MonthPoint[]>("engagement-over-time", s);
export const fetchTopContent = (s: Scope) => metric<TopContent[]>("top-content", s);
export const fetchClusterPerformance = (s: Scope) => metric<ClusterPerf[]>("cluster-performance", s);
export const fetchBenchmark = (s: Scope) => metric<Benchmark>("benchmark", s);

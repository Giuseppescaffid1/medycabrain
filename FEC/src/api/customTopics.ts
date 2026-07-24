import { apiClient } from "./client";
import type { ReelListItem } from "./types";
import type { Scope } from "./endpoints";

/** A client-supplied theme mapped onto the content by semantic similarity
 *  (e.g. "Tiroide", "Osteoporosi", "Bijuva"). */
export interface CustomTopic {
  id: number;
  label: string;
  keywords: string[];
  is_active: boolean;
  created_at: string;
  medyca_matches: number;
  competitor_matches: number;
  doc_matches: number;
}

export interface TopicMatches {
  reels: (ReelListItem & { similarity: number })[];
  docs: { id: number; title: string; url: string; summary_it: string; similarity: number }[];
}

export async function fetchCustomTopics(): Promise<CustomTopic[]> {
  const { data } = await apiClient.get("/custom-topics/");
  return Array.isArray(data) ? data : data.results;
}

export async function addCustomTopic(label: string): Promise<CustomTopic> {
  const { data } = await apiClient.post("/custom-topics/", { label });
  return data;
}

export async function deleteCustomTopic(id: number): Promise<void> {
  await apiClient.delete(`/custom-topics/${id}/`);
}

export async function fetchTopicMatches(id: number, scope: Scope): Promise<TopicMatches> {
  const { data } = await apiClient.get(`/custom-topics/${id}/matches/`, { params: { scope } });
  return data;
}

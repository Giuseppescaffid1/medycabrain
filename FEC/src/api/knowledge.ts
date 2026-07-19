import { apiClient } from "./client";
import type { Paginated } from "./types";

export interface KnowledgeDoc {
  id: number;
  source_type: string;
  source_url: string;
  title: string;
  author: string;
  published_at: string | null;
  summary_it: string;
  topics: string[];
  enrich_status: string;
  created_at: string;
}

export interface KnowledgeHit {
  kind: "blog" | "reel";
  id: number;
  title: string;
  url: string;
  summary: string;
  topics: string[];
  snippet: string;
  score: number;
}

export interface AskResult {
  answer: string;
  sources: KnowledgeHit[];
}

export async function fetchKnowledgeDocs(search?: string): Promise<KnowledgeDoc[]> {
  const { data } = await apiClient.get<Paginated<KnowledgeDoc> | KnowledgeDoc[]>(
    "/knowledge/documents/",
    { params: { search: search || undefined, page_size: 100 } }
  );
  return Array.isArray(data) ? data : data.results;
}

export async function searchKnowledge(query: string, topK = 6): Promise<KnowledgeHit[]> {
  const { data } = await apiClient.post<{ results: KnowledgeHit[] }>("/knowledge/search/", {
    query,
    top_k: topK,
  });
  return data.results;
}

export async function askKnowledge(query: string, topK = 5): Promise<AskResult> {
  // RAG runs a local LLM on CPU — can take a couple of minutes.
  const { data } = await apiClient.post<AskResult>(
    "/knowledge/ask/",
    { query, top_k: topK },
    { timeout: 300000 }
  );
  return data;
}

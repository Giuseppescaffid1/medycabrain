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
  owner?: "owned" | "competitor";
  account?: string;
  cited?: boolean;
  keyword_match?: number;
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
  model?: string;
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

export interface AskOptions {
  scope?: "all" | "medyca" | "competitor";
  history?: { role: "user" | "assistant"; content: string }[];
  topK?: number;
}

export async function askKnowledge(query: string, opts: AskOptions = {}): Promise<AskResult> {
  // No streaming: the whole answer arrives at once, in roughly 30s.
  const { data } = await apiClient.post<AskResult>(
    "/knowledge/ask/",
    {
      query,
      top_k: opts.topK ?? 8,
      scope: opts.scope ?? "all",
      history: opts.history ?? [],
    },
    { timeout: 300000 }
  );
  return data;
}

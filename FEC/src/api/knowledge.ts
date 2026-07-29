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
  primary_topic?: string;
  owner_type?: "owned" | "competitor";
  language?: string;
  source?: { id: number; name: string; owner_type: string } | null;
  enrich_status: string;
  created_at: string;
}

export interface KnowledgeDocDetail extends KnowledgeDoc {
  content_md: string;
  embed_status: string;
  updated_at: string;
  arguments?: { id: number; text_it: string; quote: string }[];
}

export interface KnowledgeHit {
  /** "external" is a page pasted into the chat, not knowledge-bank material. */
  owner?: "owned" | "competitor" | "external";
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
  /** Pages that could not be read, with the reason. */
  reference_problems?: { url: string; error: string }[];
  model?: string;
  answer: string;
  sources: KnowledgeHit[];
}

export async function fetchKnowledgeDoc(id: number): Promise<KnowledgeDocDetail> {
  const { data } = await apiClient.get<KnowledgeDocDetail>(`/knowledge/documents/${id}/`);
  return data;
}

export async function fetchKnowledgeDocs(
  search?: string,
  scope: "medyca" | "competitor" = "medyca"
): Promise<KnowledgeDoc[]> {
  const { data } = await apiClient.get<Paginated<KnowledgeDoc> | KnowledgeDoc[]>(
    "/knowledge/documents/",
    { params: { search: search || undefined, scope, page_size: 100 } }
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
  /** Pages to read for this question only. Never added to the knowledge bank. */
  references?: string[];
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
      references: opts.references ?? [],
    },
    { timeout: 300000 }
  );
  return data;
}

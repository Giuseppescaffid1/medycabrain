export interface Account {
  id: number;
  username: string;
  display_name: string;
  ig_user_id: string;
  profile_pic_url: string;
  bio: string;
  followers_count: number | null;
  owner_type: "owned" | "competitor";
  is_active: boolean;
  notes: string;
  last_scraped_at: string | null;
  reel_count?: number;
  created_at: string;
}

export interface Tag {
  id: number;
  name: string;
  color: string;
}

export interface Annotation {
  is_favorite: boolean;
  is_inspiration: boolean;
  note: string;
  tags: Tag[];
  updated_at?: string;
}

export interface ReelListItem {
  id: number;
  shortcode: string;
  account_username: string;
  caption: string;
  posted_at: string | null;
  duration_s: number | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  thumbnail_file: string;
  thumbnail_url: string;
  summary_it: string;
  content_format: string;
  is_favorite: boolean;
  is_inspiration: boolean;
  cluster_label: string | null;
  transcribe_status: string;
  enrich_status: string;
  evidence?: "transcript" | "caption_only" | "insufficient" | "";
  is_on_topic?: boolean;
  is_active?: boolean;
}

export interface Transcript {
  text: string;
  language: string;
  segments: { start: number; end: number; text: string }[];
  audio_duration_s: number | null;
  model_name: string;
}

export interface Enrichment {
  summary_it: string;
  topics: string[];
  hook_text: string;
  hook_analysis_it: string;
  target_audience_it: string;
  content_format: string;
  llm_model: string;
  evidence?: string;
  is_on_topic?: boolean;
  off_topic_reason?: string;
}

export interface ReelDetail {
  is_active?: boolean;
  id: number;
  shortcode: string;
  account: Account;
  caption: string;
  posted_at: string | null;
  duration_s: number | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  thumbnail_file: string;
  thumbnail_url: string;
  audio_file: string;
  audio_info: Record<string, unknown>;
  instagram_url: string;
  transcript: Transcript | null;
  enrichment: Enrichment | null;
  annotation: Annotation | null;
  arguments: { text: string; quote: string }[];
  media_status: string;
  transcribe_status: string;
  enrich_status: string;
  argument_status: string;
}

export interface Cluster {
  id: number;
  label_it: string;
  description_it: string;
  size: number;
  keywords: string[];
  position: number;
  preview_thumbs: string[];
  has_blog: boolean;
  reel_count: number;
  doc_count: number;
}

export interface ClusterArgument {
  text: string;
  reel_count: number;
  reels: string[];
}

export interface ScopeStats {
  accounts: number;
  reels: number;
  transcribed: number;
  enriched: number;
  clusters: number;
  last_cluster_run: string | null;
}

export interface Stats {
  competitor: ScopeStats;
  medyca: ScopeStats;
  knowledge_docs: number;
  favorites: number;
  inspiration: number;
  content_ideas: number;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

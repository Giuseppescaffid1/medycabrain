import { apiClient } from "./client";

/** One model call that is open right now: a line under its stage's bar. */
export interface ProgressItem {
  label: string;
  kind: string;
  provider: string;
  model: string;
  is_local: boolean;
  state: "waiting" | "reading" | "writing" | "running";
  seconds: number;
  tokens: number | null;
  tokens_per_second: number | null;
  max_tokens: number | null;
  usual_remaining_seconds: number | null;
  max_remaining_seconds: number | null;
  longer_than_usual: boolean;
  process: string;
  process_label?: string;
}

export interface PhaseSummary {
  phase: string;
  total: number | null;
  done: number;
  failed: number;
  skipped: number;
  unit: string;
  seconds: number;
}

export type StageStatus = "waiting" | "running" | "done" | "failed";

export interface StageData {
  id: number;
  stage: string;
  label: string;
  status: StageStatus;
  error: string;
  note: string;
  total: number | null;
  done: number;
  failed: number;
  skipped: number;
  unit: string;
  phase: string;
  phases: PhaseSummary[];
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number;
  phase_seconds: number;
  rate_per_minute: number | null;
  rate_source: "measured" | "previous" | null;
  eta_seconds: number | null;
  tokens_per_second: number | null;
  who: string;
  current: { kind: string; id: number | null; label: string; who: string } | null;
  items: ProgressItem[];
  items_more: number;
  interrupted: boolean;
}

export interface RoundData {
  run_id: string;
  source: "cron" | "manual" | "command";
  job_id: number | null;
  active: boolean;
  started_at: string | null;
  finished_at: string | null;
  interrupted: boolean;
  stages: StageData[];
}

export interface ProgressJob {
  id: number;
  kind: string;
  kind_label: string;
  status: string;
  progress: number;
  message: string;
  created_at: string;
}

export interface BatchData {
  id: number;
  kind: string;
  kind_label: string;
  items: number;
  status: string;
  model: string;
  submitted_at: string;
  expected_by: string;
  counts: Record<string, number>;
}

export interface ProgressPayload {
  now: string;
  running: boolean;
  rounds: RoundData[];
  other_calls: ProgressItem[];
  jobs: ProgressJob[];
  batches: BatchData[];
}

export interface DailyPayload {
  day: string;
  by_process: {
    process: string;
    label: string;
    calls: number;
    machine_seconds: number;
    wait_seconds: number;
    tokens_in: number;
    tokens_out: number;
    failed: number;
    transcription_seconds: number;
  }[];
  total_machine_seconds: number;
  total_wait_seconds: number;
  remote: { calls: number; seconds: number; tokens_in: number; tokens_out: number; failed: number };
  speed: { tokens_per_second: number | null; model: string; samples: number };
}

export async function fetchProgress(): Promise<ProgressPayload> {
  const { data } = await apiClient.get("/ops/progress/");
  return data;
}

export async function fetchDaily(day: string): Promise<DailyPayload> {
  const { data } = await apiClient.get("/ops/llm/", { params: { day } });
  return data;
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getJob,
  listActiveJobs,
  startClusterBlogJob,
  startIdeationJob,
  type Job,
} from "../api/jobs";
import { analyzeInput, generateDraft } from "../api/strategy";

interface JobsState {
  /** Jobs to surface in the status bar (active + recently finished). */
  jobs: Job[];
  startIdeation: (n?: number) => Promise<void>;
  startClusterBlog: (clusterId: number) => Promise<void>;
  startStrategy: (input: string, sourceKind?: string) => Promise<void>;
  startDraft: (briefId: number) => Promise<void>;
  startPlan: (n?: number, theme?: string) => Promise<void>;
  dismiss: (id: number) => void;
}

const JobsContext = createContext<JobsState | undefined>(undefined);
const POLL_MS = 3000;
const KEEP_FINISHED_MS = 6000; // keep a done/failed job visible briefly

export function JobsProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [jobs, setJobs] = useState<Job[]>([]);
  const timer = useRef<number | null>(null);
  const finishedAt = useRef<Record<number, number>>({});

  const clearTimer = () => {
    if (timer.current) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
  };

  const poll = useCallback(async () => {
    let active: Job[] = [];
    try {
      active = await listActiveJobs();
    } catch {
      return;
    }
    setJobs((prev) => {
      const now = Date.now();
      const activeIds = new Set(active.map((j) => j.id));
      // Jobs that were tracked but are no longer active → fetch final state once.
      const justFinished = prev.filter((j) => !activeIds.has(j.id) && j.status !== "done" && j.status !== "failed");
      justFinished.forEach(async (j) => {
        try {
          const final = await getJob(j.id);
          finishedAt.current[j.id] = Date.now();
          setJobs((p) => p.map((x) => (x.id === j.id ? final : x)));
          if (final.kind === "ideation" || final.kind === "editorial")
            qc.invalidateQueries({ queryKey: ["ideas"] });
          if (final.kind === "blog") qc.invalidateQueries({ queryKey: ["blog-drafts"] });
          if (final.kind === "strategy" || final.kind === "strategy_draft")
            qc.invalidateQueries({ queryKey: ["briefs"] });
          qc.invalidateQueries({ queryKey: ["stats"] });
        } catch {
          /* ignore */
        }
      });
      // Merge active jobs in; keep finished ones for a short grace period.
      const merged: Record<number, Job> = {};
      prev.forEach((j) => (merged[j.id] = j));
      active.forEach((j) => (merged[j.id] = j));
      return Object.values(merged).filter((j) => {
        if (activeIds.has(j.id)) return true;
        const done = finishedAt.current[j.id];
        return done ? now - done < KEEP_FINISHED_MS : j.status !== "done" && j.status !== "failed";
      });
    });
  }, [qc]);

  // Poll only while there is something to watch.
  useEffect(() => {
    const hasActive = jobs.some((j) => j.status === "queued" || j.status === "running");
    if (hasActive && !timer.current) {
      timer.current = window.setInterval(poll, POLL_MS);
    } else if (!hasActive && timer.current) {
      clearTimer();
    }
    return () => {
      /* keep timer across renders; cleared when no active jobs */
    };
  }, [jobs, poll]);

  useEffect(() => () => clearTimer(), []);

  const registerJob = useCallback((job: Job) => {
    setJobs((prev) => [job, ...prev.filter((j) => j.id !== job.id)]);
    if (!timer.current) timer.current = window.setInterval(poll, POLL_MS);
    poll();
  }, [poll]);

  const startPlan = useCallback(async (n = 6, theme = "") => {
    const { startPlanJob } = await import("../api/secondBrain");
    registerJob(await startPlanJob(n, theme));
  }, [registerJob]);

  const startIdeation = useCallback(async (n = 8) => {
    registerJob(await startIdeationJob(n));
  }, [registerJob]);

  const startClusterBlog = useCallback(async (clusterId: number) => {
    registerJob(await startClusterBlogJob(clusterId));
  }, [registerJob]);

  const startStrategy = useCallback(async (input: string, sourceKind = "input") => {
    registerJob(await analyzeInput(input, sourceKind));
  }, [registerJob]);

  const startDraft = useCallback(async (briefId: number) => {
    registerJob(await generateDraft(briefId));
  }, [registerJob]);

  const dismiss = useCallback((id: number) => {
    setJobs((prev) => prev.filter((j) => j.id !== id));
  }, []);

  return (
    <JobsContext.Provider
      value={{ jobs, startIdeation, startClusterBlog, startStrategy, startDraft,
        startPlan, dismiss }}
    >
      {children}
    </JobsContext.Provider>
  );
}

export function useJobs() {
  const ctx = useContext(JobsContext);
  if (!ctx) throw new Error("useJobs must be used within JobsProvider");
  return ctx;
}

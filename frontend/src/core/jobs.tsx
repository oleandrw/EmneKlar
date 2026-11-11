// One source of truth for background jobs. The status panel in the header, the local status in a page's own button
// and the inline status of a job started on a page all read from here, so they always show the same thing.
//
// * Polls GET /api/jobs (the jobs in this run of EmneKlar): every second while something runs, otherwise every
//   10 seconds. Live updates from a job's event stream (useJob) are merged into the same list.
// * Jobs that were running when EmneKlar stopped are marked «avbrutt» by the backend; the job history from the
//   database brings them (and the last finished jobs) back after a restart. Nothing pretends to continue.
// * A job the user has just started opens the panel once, as a confirmation (without moving focus). Progress updates
//   never open it again.
// * The history from the database also brings back every unresolved job (failed or interrupted), however old –
//   they stay until the teacher hides them («Skjul») or a new attempt replaces them. Hiding and «Fjern fullførte»
//   only tidy this overview (kept in this browser); results and the stored history are never touched.
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useToast } from "../design-system";
import { api } from "./api/client";
import type { Job } from "./api/types";
import { useCurrentCourse } from "./course";
import {
  analysesFor,
  describeJob,
  isActive,
  isFinal,
  jobName,
  newerJob,
  retryRequest,
  STATUS_LABEL,
} from "./jobs-model";
import { useSession } from "./session";

export const JOBS_LIST_KEY = ["jobs", "list"] as const;
const HISTORY_KEY = ["jobs", "history"] as const;
const HIDDEN_STORAGE = "emneklar.jobs.hidden";
/** Read once for compatibility: jobs marked as seen by the earlier version count as hidden. */
const LEGACY_SEEN_STORAGE = "emneklar.jobs.seen";
const CLEARED_STORAGE = "emneklar.jobs.finishedClearedAt";
/** Without a successful update for this long while something runs, the status is shown as possibly out of date. */
export const STALE_MS = 15_000;
/** Finished jobs kept in the list (running jobs are always included). */
const FINISHED_LIMIT = 20;

interface JobList {
  jobs: Job[];
}

/** Puts a job snapshot into the shared list (newest snapshot wins), e.g. from a job's event stream. */
export function upsertJob(client: QueryClient, job: Job) {
  client.setQueryData<JobList>(JOBS_LIST_KEY, (old) => {
    if (!old) return { jobs: [job] };
    const index = old.jobs.findIndex((j) => j.id === job.id);
    if (index < 0) return { jobs: [job, ...old.jobs] };
    const merged = newerJob(old.jobs[index], job);
    if (merged === old.jobs[index]) return old;
    const jobs = [...old.jobs];
    jobs[index] = merged;
    return { jobs };
  });
}

function readIds(key: string): string[] {
  try {
    const raw = window.localStorage.getItem(key);
    const ids = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function readHidden(): Set<string> {
  return new Set([...readIds(LEGACY_SEEN_STORAGE), ...readIds(HIDDEN_STORAGE)]);
}

function readClearedAt(): number {
  try {
    return Number(window.localStorage.getItem(CLEARED_STORAGE)) || 0;
  } catch {
    return 0;
  }
}

/** Private window or blocked storage: the choice lasts until the page is reloaded. */
function store(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignored – see above
  }
}

export interface JobsValue {
  /** Live jobs and jobs from the history (unordered – see compactJobs). */
  jobs: Job[];
  loaded: boolean;
  /** Lost contact with EmneKlar, or no update for a while: the status may be out of date. */
  stale: boolean;
  /** When the status was last updated (ms), 0 before the first update. */
  updatedAt: number;
  /** Jobs hidden from the compact overview («Skjul»). */
  hidden: ReadonlySet<string>;
  hide: (ids: string[]) => void;
  /** Finished jobs before this time (ms) are left out of the overview («Fjern fullførte»). */
  clearedAt: number;
  clearFinished: () => void;
  panelOpen: boolean;
  setPanelOpen: (open: boolean) => void;
  /** Opens the panel and moves focus to it («Vis i Analysestatus» on a page). Changes every time it is asked. */
  revealPanel: () => void;
  focusRequest: number;
  /** A job the user has just started: show it at once and open the panel as a confirmation. */
  track: (job: Job) => void;
  /** Starts an analysis again with the same choices (only analyses – see retryRequest). */
  retry: (job: Job) => Promise<Job>;
}

const NOOP_VALUE: JobsValue = {
  jobs: [],
  loaded: false,
  stale: false,
  updatedAt: 0,
  hidden: new Set(),
  hide: () => {},
  clearedAt: 0,
  clearFinished: () => {},
  panelOpen: false,
  setPanelOpen: () => {},
  revealPanel: () => {},
  focusRequest: 0,
  track: () => {},
  retry: () => Promise.reject(new Error("Jobbstatus er ikke tilgjengelig.")),
};

const JobsContext = createContext<JobsValue | null>(null);

function useNow(intervalMs: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (intervalMs === null) return;
    const handle = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(handle);
  }, [intervalMs]);
  return now;
}

/** Results on every page may have changed when a job finishes – refetch them (not the job list or the session). */
const RESULT_KEYS_TO_KEEP = new Set(["jobs", "session", "courses"]);

export function JobsProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const toast = useToast();
  const session = useSession();
  const [panelOpen, setPanelOpen] = useState(false);
  const panelOpenRef = useRef(panelOpen);
  panelOpenRef.current = panelOpen;
  const [hidden, setHidden] = useState<Set<string>>(readHidden);
  const [clearedAt, setClearedAt] = useState<number>(readClearedAt);
  const [focusRequest, setFocusRequest] = useState(0);
  const [announcement, setAnnouncement] = useState("");

  const live = useQuery({
    queryKey: JOBS_LIST_KEY,
    queryFn: () => api.get<JobList>(`/api/jobs?limit=${FINISHED_LIMIT}`),
    refetchInterval: (query) => (query.state.data?.jobs.some(isActive) ? 1_000 : 10_000),
    staleTime: 0,
  });
  // The history: the last jobs (also from earlier runs of EmneKlar), and every unresolved one however old.
  const history = useQuery({
    queryKey: [...HISTORY_KEY, "recent"],
    queryFn: () => api.get<JobList>("/api/jobs/history?limit=20"),
    staleTime: Infinity,
  });
  const unresolvedHistory = useQuery({
    queryKey: [...HISTORY_KEY, "unresolved"],
    queryFn: () => api.get<JobList>("/api/jobs/history?status=failed,interrupted,cancelled&limit=100"),
    staleTime: Infinity,
  });

  const jobs = useMemo(() => {
    const byId = new Map<string, Job>();
    for (const job of [...(unresolvedHistory.data?.jobs ?? []), ...(history.data?.jobs ?? [])]) {
      // The live list is the truth for running jobs; the history adds how earlier jobs ended.
      if (isFinal(job)) byId.set(job.id, { ...job, progress: job.progress ?? {} } as Job);
    }
    for (const job of live.data?.jobs ?? []) byId.set(job.id, job);
    return [...byId.values()];
  }, [live.data, history.data, unresolvedHistory.data]);

  // Keep a job's own query (useJob) in step with the list.
  useEffect(() => {
    for (const job of live.data?.jobs ?? []) {
      const key = ["jobs", job.id];
      const cached = client.getQueryData<Job>(key);
      if (cached !== undefined) {
        const merged = newerJob(cached, job);
        if (merged !== cached) client.setQueryData(key, merged);
      }
    }
  }, [live.data, client]);

  // New jobs open the panel once; active jobs that disappeared mean EmneKlar restarted – ask the history.
  const known = useRef<Set<string> | null>(null);
  useEffect(() => {
    const list = live.data?.jobs;
    if (!list) return;
    if (known.current === null) {
      known.current = new Set(list.map((j) => j.id));
      return;
    }
    let opened = false;
    for (const job of list) {
      if (known.current.has(job.id)) continue;
      known.current.add(job.id);
      opened = true;
      if (isActive(job)) setAnnouncement(`${jobName(job)} er startet.`);
    }
    if (opened) setPanelOpen(true);
  }, [live.data]);

  // Finished jobs: refresh the results, announce it, and (for analyses) the notification the user chose.
  const statuses = useRef<Map<string, { status: Job["status"]; known: boolean }> | null>(null);
  const notifySettings = session.notifications;
  useEffect(() => {
    if (!live.data) return;
    const first = statuses.current === null;
    const previous = statuses.current ?? new Map<string, { status: Job["status"]; known: boolean }>();
    const next = new Map<string, { status: Job["status"]; known: boolean }>();
    let finished: Job | null = null;
    let vanished = false;
    const ids = new Set(jobs.map((j) => j.id));
    for (const [id, before] of previous) {
      if (!ids.has(id) && !isFinal({ status: before.status })) vanished = true;
    }
    const liveIds = new Set(live.data.jobs.map((j) => j.id));
    for (const job of jobs) {
      const before = previous.get(job.id);
      const bar = describeJob(job).bar;
      next.set(job.id, { status: job.status, known: bar?.kind === "known" });
      if (first) continue;
      if (isFinal(job)) {
        // It ran while EmneKlar was open here – or it was started and finished between two updates.
        const ended = before ? !isFinal({ status: before.status }) : liveIds.has(job.id);
        if (ended) finished = job;
      } else if (before && bar?.kind === "known" && !before.known) {
        setAnnouncement(`${jobName(job)}: ${bar.counts} totalt.`);
      }
    }
    statuses.current = next;
    if (vanished) void client.invalidateQueries({ queryKey: HISTORY_KEY });
    if (!finished) return;
    const job = finished;
    void client.invalidateQueries({ predicate: (query) => !RESULT_KEYS_TO_KEEP.has(String(query.queryKey[0])) });
    const name = jobName(job);
    setAnnouncement(job.status === "completed" ? `${name} er fullført.`
      : job.status === "failed" ? `${name} feilet. ${job.error ?? ""}`.trim()
      : `${name} ble avbrutt.`);
    if (job.kind !== "analysis" || !notifySettings.notify_job_complete) return;
    const ok = job.status === "completed";
    if (!panelOpenRef.current) {
      toast.show({
        tone: ok ? "success" : job.status === "failed" ? "danger" : "warning",
        title: ok ? "Analysen er ferdig" : `Analysen ble ${job.status === "failed" ? "ikke fullført" : "avbrutt"}`,
        body: ok ? "Resultatene er oppdatert." : (job.error ?? undefined),
      });
    }
    if (notifySettings.browser_notifications && "Notification" in window && Notification.permission === "granted") {
      new Notification("EmneKlar", { body: ok ? "Analysen er ferdig." : "Analysen ble ikke fullført." });
    }
  }, [jobs, live.data, client, toast, notifySettings]);

  const hasActive = jobs.some(isActive);
  const now = useNow(hasActive ? 5_000 : null);
  const updatedAt = live.dataUpdatedAt;
  const stale = Boolean(live.data) && (live.isError
    || (hasActive && updatedAt > 0 && now - updatedAt > STALE_MS && typeof document !== "undefined" && !document.hidden));

  const hide = useCallback((ids: string[]) => {
    setHidden((current) => {
      const next = new Set(current);
      for (const id of ids) next.add(id);
      store(HIDDEN_STORAGE, JSON.stringify([...next].slice(-500)));
      return next;
    });
  }, []);

  const clearFinished = useCallback(() => {
    const at = Date.now();
    setClearedAt(at);
    store(CLEARED_STORAGE, String(at));
  }, []);

  const track = useCallback((job: Job) => {
    known.current?.add(job.id);
    upsertJob(client, job);
    setPanelOpen(true);
    setAnnouncement(`${jobName(job)} er startet.`);
  }, [client]);

  const retry = useCallback(async (job: Job) => {
    const body = retryRequest(job);
    if (!body) throw new Error("Denne jobben kan ikke startes på nytt herfra.");
    // Same course, kind and scope: the new attempt takes over the row of the one that stopped.
    const created = await api.post<Job>("/api/analysis", body);
    track(created);
    return created;
  }, [track]);

  const revealPanel = useCallback(() => {
    setPanelOpen(true);
    setFocusRequest((n) => n + 1);
  }, []);

  const value = useMemo<JobsValue>(() => ({
    jobs, loaded: Boolean(live.data), stale, updatedAt, hidden, hide, clearedAt, clearFinished, panelOpen, setPanelOpen,
    revealPanel, focusRequest, track, retry,
  }), [jobs, live.data, stale, updatedAt, hidden, hide, clearedAt, clearFinished, panelOpen, revealPanel, focusRequest,
    track, retry]);

  return (
    <JobsContext.Provider value={value}>
      {children}
      {/* Start, a known total and the end of each job – never every percentage. */}
      <div className="ek-visually-hidden" role="status" aria-live="polite" aria-atomic="true">{announcement}</div>
    </JobsContext.Provider>
  );
}

export function useJobs(): JobsValue {
  return useContext(JobsContext) ?? NOOP_VALUE;
}

/** Analyses of the current course. ``running``: any analysis of the course now (EmneKlar runs one analysis per course
 *  at a time, so it blocks starting another). ``runningHere``: one that covers ``domain``. ``latest``: the newest one
 *  that covers ``domain``, running or not. Without a domain, every analysis of the course counts. */
export function useCourseAnalysis(domain?: string): {
  running: Job | null;
  runningHere: Job | null;
  latest: Job | null;
  courseId: string | null;
} {
  const { jobs } = useJobs();
  const { courseId } = useCurrentCourse();
  return useMemo(() => {
    const newest = (list: Job[]) => [...list].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    const mine = newest(analysesFor(jobs, courseId, domain));
    return {
      running: newest(analysesFor(jobs, courseId)).find(isActive) ?? null,
      runningHere: mine.find(isActive) ?? null,
      latest: mine[0] ?? null,
      courseId: courseId ?? null,
    };
  }, [jobs, courseId, domain]);
}

/** A job from the shared list (for the inline status of a job started on a page). */
export function useListedJob(jobId: string | null): Job | null {
  const { jobs } = useJobs();
  return useMemo(() => (jobId ? jobs.find((j) => j.id === jobId) ?? null : null), [jobs, jobId]);
}

export { STATUS_LABEL };

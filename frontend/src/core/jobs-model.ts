// What a background job is doing, in words. One description is used by the status panel in the header and by the
// local status in a page's own button, so both always show the same activity and the same numbers.
//
// The numbers come only from the job's real progress (tasks known to exist and tasks actually finished). While the
// total is unknown there is no percentage – the bar shows activity, and the text says the number is not known yet.
import type { Job, JobProgress } from "./api/types";
import { formatNumber, formatWhen } from "./format";
import { DOMAIN_LABEL, type Domain } from "./labels";

export const ACTIVE_STATUSES: ReadonlySet<Job["status"]> = new Set(["queued", "running", "pausing", "paused", "cancelling"]);
export const FINAL_STATUSES: ReadonlySet<Job["status"]> = new Set(["completed", "failed", "cancelled", "interrupted"]);

export const isActive = (job: Pick<Job, "status">) => ACTIVE_STATUSES.has(job.status);
export const isFinal = (job: Pick<Job, "status">) => FINAL_STATUSES.has(job.status);
/** A job that did not finish – it failed, EmneKlar was closed while it ran, or it was cancelled. It stays in the
 *  overview (with a warning symbol) until the user hides it or a new attempt replaces it. Findings in the course are
 *  never a job error: an analysis that finds broken links is «Fullført». */
export const isProblem = (job: Pick<Job, "status">) =>
  job.status === "failed" || job.status === "interrupted" || job.status === "cancelled";

export type JobState = "running" | "waiting" | "paused" | "stopping" | "completed" | "failed" | "interrupted" | "cancelled";

const STATE: Record<Job["status"], JobState> = {
  queued: "waiting",
  running: "running",
  pausing: "paused",
  paused: "paused",
  cancelling: "stopping",
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
  interrupted: "interrupted",
};

export const STATUS_LABEL: Record<Job["status"], string> = {
  queued: "Venter",
  running: "Pågår",
  pausing: "Settes på pause",
  paused: "På pause",
  cancelling: "Avbryter",
  completed: "Fullført",
  failed: "Feilet",
  cancelled: "Avbrutt",
  interrupted: "Avbrutt",
};

const SCOPE_LABEL: Record<string, string> = { modules: "valgte moduler", items: "valgte elementer" };

/** «Innholdskvalitet», «Universell utforming – valgte elementer», or the job's own title. */
export function jobName(job: Pick<Job, "kind" | "title" | "params">): string {
  if (job.kind !== "analysis") return job.title;
  const domains = (job.params?.domains ?? []) as string[];
  const scope = SCOPE_LABEL[String(job.params?.scope ?? "course")];
  if (domains.length === 1 && domains[0] in DOMAIN_LABEL) {
    const label = DOMAIN_LABEL[domains[0] as Domain];
    return scope ? `${label} – ${scope}` : label;
  }
  return job.title;
}

export interface JobCounts {
  done: number;
  total: number;
  failed: number;
  /** «sider», «lenker» – or «elementer» when the job counts several kinds of work. */
  unit: string;
}

/** «Sider» → «sider»; «KI-forespørsler» keeps its capitals. */
function unitOf(label: string): string {
  return label.length > 1 && label[1] === label[1].toLowerCase() ? label[0].toLowerCase() + label.slice(1) : label;
}

/** The work the job has counted. Fetching the content lists from Canvas is preparation, not the work itself: once
 *  there is other work, the lists are left out (so «124 av 380» counts what the user thinks of as the content). */
export function jobCounts(progress: Partial<JobProgress> | undefined): JobCounts | null {
  const entries = Object.entries(progress?.types ?? {}).filter(([, t]) => t.total > 0);
  const work = entries.filter(([key]) => key !== "list");
  const counted = work.length ? work : entries;
  if (!counted.length) return null;
  const total = counted.reduce((sum, [, t]) => sum + t.total, 0);
  const done = Math.min(total, counted.reduce((sum, [, t]) => sum + t.done, 0));
  const failed = counted.reduce((sum, [, t]) => sum + t.failed, 0);
  return { done, total, failed, unit: counted.length === 1 ? unitOf(counted[0][1].label) : "elementer" };
}

export type JobBar =
  /** The total is known: a filled bar, the count and the percentage. */
  | { kind: "known"; percent: number; counts: string }
  /** The total is not known yet: a moving segment (no fill), and a text that says so. */
  | { kind: "unknown"; detail: string };

export interface JobDescription {
  state: JobState;
  /** «Pågår», «Venter», «Fullført», «Feilet», «Avbrutt» … */
  status: string;
  /** What it is doing now – or, when it has stopped, what happened. */
  activity: string;
  /** «Steg 2 av 3» when the job has several steps. */
  step: string | null;
  bar: JobBar | null;
  /** When the numbers do not cover the whole job (later steps are not counted yet). */
  note: string | null;
  /** The compact text for the page's own button: «Analyserer innholdet · 124 av 380». */
  button: string;
}

const strip = (label: string) => label.replace(/\s*(…|\.\.\.)\s*$/, "").trim();
const checks = (kind: string) => kind === "analysis" || kind === "quiz_review";

/** What a finished job did: «380 av 380 elementer kontrollert · 42 funn». */
export function jobSummary(job: Job): string {
  const counts = jobCounts(job.progress);
  const verb = checks(job.kind) ? "kontrollert" : "behandlet";
  const parts: string[] = [];
  if (counts) {
    parts.push(`${formatNumber(counts.done - counts.failed)} av ${formatNumber(counts.total)} ${counts.unit} ${verb}`);
    if (counts.failed) parts.push(`${formatNumber(counts.failed)} kunne ikke ${checks(job.kind) ? "kontrolleres" : "behandles"}`);
  }
  if (job.kind === "analysis") {
    const findings = Object.values(job.progress?.findings ?? {}).reduce((sum, n) => sum + n, 0);
    if (findings > 0) parts.push(`${formatNumber(findings)} funn`);
  }
  return parts.length ? parts.join(" · ") : "Ferdig";
}

export function describeJob(job: Job): JobDescription {
  const p: Partial<JobProgress> = job.progress ?? {};
  const counts = jobCounts(p);
  const steps = p.phase_count ?? 1;
  const index = Math.max(1, p.phase_index ?? 1);
  const step = steps > 1 ? `Steg ${Math.min(index, steps)} av ${steps}` : null;
  const status = STATUS_LABEL[job.status];
  const state = STATE[job.status];
  const base = { state, status, step: null as string | null, bar: null as JobBar | null, note: null as string | null };

  switch (job.status) {
    case "queued":
      return { ...base, activity: "Venter på å starte", button: "Venter på å starte …" };
    case "completed": {
      const partial = (job.result as { status?: string } | undefined)?.status === "partial";
      return { ...base, activity: jobSummary(job), button: "Fullført",
        note: partial ? "Noe innhold kunne ikke hentes eller kontrolleres – se begrensningene ved resultatene." : null };
    }
    case "failed":
      return { ...base, activity: job.error || "Jobben stoppet på grunn av en feil.", button: "Feilet" };
    case "interrupted":
      return { ...base, activity: job.error || "EmneKlar ble avsluttet mens jobben kjørte.", button: "Avbrutt" };
    case "cancelled":
      return { ...base, button: "Avbrutt", activity: counts && counts.done < counts.total
        ? `Du avbrøt jobben etter ${formatNumber(counts.done)} av ${formatNumber(counts.total)} ${counts.unit}.`
        : "Du avbrøt jobben." };
    default:
      break;
  }

  // Running, pausing, paused or cancelling.
  const preparing = !p.phase || p.phase === "queued";
  const activity = preparing ? (checks(job.kind) ? "Forbereder kontrollen" : "Forbereder") : strip(p.phase_label ?? "") || "Arbeider";
  const known = Boolean(p.determinate && counts);
  const bar: JobBar = known && counts
    ? { kind: "known", percent: Math.min(100, Math.floor((counts.done * 100) / counts.total)),
        counts: `${formatNumber(counts.done)} av ${formatNumber(counts.total)} ${counts.unit}` }
    : { kind: "unknown", detail: counts
        ? `Antall foreløpig ukjent – ${formatNumber(counts.done)} av ${formatNumber(counts.total)} ${counts.unit} ferdig`
        : "Antall foreløpig ukjent" };
  const note = known && step && index < steps
    ? `Tallene gjelder ${index === 1 ? "steg 1" : `steg 1–${index}`} av ${steps}, ikke hele jobben.`
    : null;
  const count = known && counts ? ` · ${formatNumber(counts.done)} av ${formatNumber(counts.total)}` : "";
  const button = job.status === "running"
    ? (known ? `${activity}${count}` : `${activity} …`)
    : job.status === "paused" ? `På pause${count}` : job.status === "pausing" ? "Settes på pause …" : "Avbryter …";
  return { state, status, step, bar, note, activity: known ? activity : `${activity} …`, button };
}

export interface JobSummary {
  /** Running (also while pausing or cancelling). */
  running: number;
  paused: number;
  waiting: number;
  /** Unresolved: stopped on an error («feilet»), or interrupted or cancelled («avbrutt») – until hidden or replaced. */
  failed: number;
  interrupted: number;
}

/** Counts the jobs it is given (pass the active and unresolved ones – see compactJobs). */
export function summarizeJobs(jobs: Job[]): JobSummary {
  const summary: JobSummary = { running: 0, paused: 0, waiting: 0, failed: 0, interrupted: 0 };
  for (const job of jobs) {
    if (job.status === "running" || job.status === "pausing" || job.status === "cancelling") summary.running += 1;
    else if (job.status === "paused") summary.paused += 1;
    else if (job.status === "queued") summary.waiting += 1;
    else if (job.status === "failed") summary.failed += 1;
    else if (job.status === "interrupted" || job.status === "cancelled") summary.interrupted += 1;
  }
  return summary;
}

/** «2 pågår · 1 avbrutt» – empty when nothing is running and nothing needs attention. */
export function summaryText(summary: JobSummary): string {
  return [
    summary.running ? `${formatNumber(summary.running)} pågår` : null,
    summary.paused ? `${formatNumber(summary.paused)} på pause` : null,
    summary.waiting ? `${formatNumber(summary.waiting)} venter` : null,
    summary.failed ? `${formatNumber(summary.failed)} feilet` : null,
    summary.interrupted ? `${formatNumber(summary.interrupted)} avbrutt` : null,
  ].filter(Boolean).join(" · ");
}

/** Rows shown directly in the panel. */
export const ROW_CAP = 10;
/** Finished jobs shown: at most this many, and only from the last day (both limits apply). */
export const RECENT_FINISHED = 4;
export const RECENT_MS = 24 * 60 * 60 * 1000;

/** Order-independent JSON: object keys sorted, arrays sorted (a module selection is the same in any order). */
function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).sort().join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value as Record<string, unknown>).sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

/** The logical job: the same kind of job for the same course and the same scope (its parameters) – never the visible
 *  title or the time. A new run of the same logical job replaces the old one in the compact overview. */
export function logicalKey(job: Pick<Job, "kind" | "course_id" | "params">): string {
  return `${job.course_id ?? "–"}|${job.kind}|${stableJson(job.params ?? {})}`;
}

const time = (value: string | null | undefined) => (value ? Date.parse(value) || 0 : 0);
const newestFirst = (a: Job, b: Job) => time(b.created_at) - time(a.created_at);
const ACTIVE_RANK: Partial<Record<Job["status"], number>> = { running: 0, pausing: 0, cancelling: 0, paused: 1, queued: 2 };

export interface CompactJobs {
  /** The rows to show, in order (running, waiting, unresolved, then recent finished). */
  rows: Job[];
  /** Every active and unresolved job (also those beyond the cap) – the header counts these. */
  pinned: Job[];
  summary: JobSummary;
  /** Active and unresolved jobs that do not fit in the short list (shown with «Vis alle …»). */
  overflow: number;
  /** Completed jobs in the short list («Sist fullførte») – «Fjern fullførte» removes these from the overview. */
  finished: Job[];
}

/**
 * The compact overview: what the teacher needs now, without tidying it by hand.
 * 1. Running and waiting jobs (never hidden or capped away).
 * 2. Unresolved jobs (failed, interrupted or cancelled) – kept whatever their age, until hidden or replaced by a new
 *    attempt.
 * 3. The last completed jobs: at most RECENT_FINISHED, from the last day, not hidden and not cleared.
 * A newer run of the same logical job replaces the older one; an active job is never replaced. At most ROW_CAP rows –
 * room goes to 1 and 2 first; ``showAll`` lists every active and unresolved job.
 */
export function compactJobs(jobs: Job[], { hidden, clearedAt = 0, now = Date.now(), showAll = false }: {
  hidden: ReadonlySet<string>;
  clearedAt?: number;
  now?: number;
  showAll?: boolean;
}): CompactJobs {
  const groups = new Map<string, Job[]>();
  for (const job of jobs) {
    const key = logicalKey(job);
    groups.set(key, [...(groups.get(key) ?? []), job]);
  }
  const current: Job[] = [];
  for (const group of groups.values()) {
    const [newest, ...older] = [...group].sort(newestFirst);
    current.push(newest, ...older.filter(isActive));
  }
  const active = current.filter(isActive)
    .sort((a, b) => (ACTIVE_RANK[a.status] ?? 3) - (ACTIVE_RANK[b.status] ?? 3) || newestFirst(a, b));
  const finishedAt = (job: Job) => time(job.finished_at ?? job.created_at);
  const unresolved = current.filter((job) => isProblem(job) && !hidden.has(job.id))
    .sort((a, b) => finishedAt(b) - finishedAt(a));
  const finished = current
    .filter((job) => job.status === "completed" && !hidden.has(job.id)
      && finishedAt(job) >= now - RECENT_MS && finishedAt(job) > clearedAt)
    .sort((a, b) => finishedAt(b) - finishedAt(a))
    .slice(0, RECENT_FINISHED);
  const pinned = [...active, ...unresolved];
  const shownPinned = showAll ? pinned : pinned.slice(0, ROW_CAP);
  const room = Math.max(0, ROW_CAP - shownPinned.length);
  const recent = finished.slice(0, room);
  return {
    rows: [...shownPinned, ...recent],
    pinned,
    summary: summarizeJobs(pinned),
    overflow: Math.max(0, pinned.length - ROW_CAP),
    finished: recent,
  };
}

/** The newest snapshot of a job wins: a status that has stopped is never replaced by an older running one. */
export function newerJob(current: Job | undefined, incoming: Job): Job {
  if (!current) return incoming;
  if (isFinal(current) && !isFinal(incoming)) return current;
  const a = current.progress?.version;
  const b = incoming.progress?.version;
  if (typeof a === "number" && typeof b === "number" && b < a && current.status === incoming.status) return current;
  return incoming;
}

/** Only an analysis can be started again from the panel with the same choices: it only reads from Canvas. Other jobs
 *  are started again where they were started (they may need choices, consent or a review first). */
export function retryRequest(job: Job): Record<string, unknown> | null {
  if (job.kind !== "analysis" || job.status === "completed" || !isFinal(job) || !job.course_id) return null;
  const params = job.params ?? {};
  const domains = params.domains;
  if (!Array.isArray(domains) || domains.length === 0) return null;
  return {
    course_id: job.course_id,
    scope: params.scope ?? "course",
    domains,
    module_ids: Array.isArray(params.module_ids) ? params.module_ids : [],
    items: Array.isArray(params.items) ? params.items : [],
  };
}

/** Where a job of this kind is started, for «Gå til …» when it cannot be started again from the panel. */
export const JOB_PLACE: Record<string, { label: string; to: string }> = {
  video_scan: { label: "Gå til Innholdskvalitet", to: "/innholdskvalitet" },
  quiz_review: { label: "Gå til Quizassistent", to: "/quizassistent" },
  bank_generate: { label: "Gå til spørsmålsbanken", to: "/quizassistent/sporsmalsbank" },
  rag_build: { label: "Gå til kunnskapsbasen", to: "/canvas-verktoy/emne-rag" },
  rag_eval: { label: "Gå til kunnskapsbasen", to: "/canvas-verktoy/emne-rag" },
  illustrations: { label: "Gå til bildeassistenten", to: "/canvas-verktoy/bildeassistent" },
  alt_text_suggestions: { label: "Gå til Universell utforming", to: "/universell-utforming" },
};

/** The analysis jobs for one course that cover a domain (all analyses of the course without a domain). */
export function analysesFor(jobs: Job[], courseId: string | null | undefined, domain?: string): Job[] {
  if (!courseId) return [];
  return jobs.filter((job) => job.kind === "analysis" && job.course_id === courseId
    && (!domain || ((job.params?.domains ?? []) as string[]).includes(domain)));
}

/** «Viser resultater fra 6. november kl. 15.42. Ny kontroll pågår.» – the time always belongs to the results shown.
 *  ``stopped`` is a newer check that did not finish (the results shown are still the earlier ones). */
export function freshnessText({ resultsAt, running, stopped, stale = false }: {
  resultsAt: string | null | undefined;
  running: boolean;
  stopped?: Job | null;
  /** Lost contact with EmneKlar: whether the new check still runs is not known. */
  stale?: boolean;
}): string | null {
  if (running && stale) {
    const unknown = "Mistet kontakten med EmneKlar – status for den nye kontrollen er ukjent.";
    return resultsAt ? `Viser resultater fra ${formatWhen(resultsAt)}. ${unknown}` : unknown;
  }
  if (running) return resultsAt ? `Viser resultater fra ${formatWhen(resultsAt)}. Ny kontroll pågår.` : "Første kontroll pågår.";
  if (stopped) {
    const why = stopped.status === "cancelled" ? "ble avbrutt" : "ble ikke fullført";
    return resultsAt
      ? `Den nye kontrollen ${why}. Viser resultater fra ${formatWhen(resultsAt)}.`
      : `Kontrollen ${why}. Det finnes ingen tidligere resultater.`;
  }
  return null;
}

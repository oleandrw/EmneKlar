import { describe, expect, it } from "vitest";

import type { Job, JobProgress } from "./api/types";
import {
  describeJob,
  freshnessText,
  jobCounts,
  jobName,
  compactJobs,
  logicalKey,
  newerJob,
  RECENT_FINISHED,
  retryRequest,
  summarizeJobs,
  summaryText,
} from "./jobs-model";

const progress = (over: Partial<JobProgress> = {}): JobProgress => ({
  phase: "analyze", phase_label: "Analyserer innholdet", phase_index: 2, phase_count: 2, determinate: true,
  percent: null, done: 0, total: 0, types: {}, current_item: null, current_operation: null, findings: {},
  eta: { state: "calculating" }, in_flight: 0, messages: [], version: 1, ...over,
});

const job = (over: Partial<Job> = {}): Job => ({
  id: "j1", kind: "analysis", course_id: "101", title: "Analyse av hele emnet", status: "running",
  params: { domains: ["content_quality"], scope: "course" }, supports_pause: true, error: null, result: {},
  created_at: "2026-11-06T14:40:00Z", started_at: "2026-11-06T14:40:00Z", finished_at: null, progress: progress(),
  ...over,
});

const LISTS = { label: "Innholdslister", total: 9, done: 9, failed: 0 };

describe("describeJob", () => {
  it("known total: the activity, a filled bar, the count without the content lists, and a percentage from the same numbers", () => {
    const d = describeJob(job({ progress: progress({ types: { list: LISTS, link: { label: "Lenker", total: 380, done: 124, failed: 0 } } }) }));
    expect(d.status).toBe("Pågår");
    expect(d.activity).toBe("Analyserer innholdet");
    expect(d.step).toBe("Steg 2 av 2");
    expect(d.bar).toEqual({ kind: "known", percent: 32, counts: "124 av 380 lenker" });
    expect(d.note, "the last step: the numbers cover the whole job").toBeNull();
    expect(d.button).toBe("Analyserer innholdet · 124 av 380");
  });

  it("unknown total: no percentage, a moving bar and a text that says the number is not known yet", () => {
    const d = describeJob(job({ progress: progress({ phase: "discover", phase_label: "Henter innhold fra Canvas", phase_index: 1,
      determinate: false, types: { list: { ...LISTS, done: 4 } } }) }));
    expect(d.bar).toEqual({ kind: "unknown", detail: "Antall foreløpig ukjent – 4 av 9 innholdslister ferdig" });
    expect(d.activity).toBe("Henter innhold fra Canvas …");
    expect(d.button).toBe("Henter innhold fra Canvas …");
    expect(JSON.stringify(d)).not.toMatch(/%/);
  });

  it("says when the numbers only cover the steps so far", () => {
    const d = describeJob(job({ kind: "rag_build", title: "Bygger kunnskapsbasen", progress: progress({ phase_label: "Dokumenter",
      phase_index: 2, phase_count: 4, types: { text: { label: "Tekst", total: 10, done: 10, failed: 0 },
        document: { label: "Dokumenter", total: 30, done: 5, failed: 0 } } }) }));
    expect(d.bar).toMatchObject({ kind: "known", counts: "15 av 40 elementer", percent: 37 });
    expect(d.note).toBe("Tallene gjelder steg 1–2 av 4, ikke hele jobben.");
  });

  it("a job that has started but not reported a step yet is preparing, not «Venter»", () => {
    const d = describeJob(job({ progress: progress({ phase: "queued", phase_label: "Venter …", determinate: false }) }));
    expect(d.activity).toBe("Forbereder kontrollen …");
    expect(describeJob(job({ status: "queued" }))).toMatchObject({ status: "Venter", state: "waiting", bar: null });
  });

  it("finished, failed, interrupted and cancelled jobs have no bar and say what happened", () => {
    const types = { list: LISTS, module: { label: "Moduler", total: 20, done: 20, failed: 0 } };
    expect(describeJob(job({ status: "completed", progress: progress({ types, findings: { "content_quality:violation": 3 } }) })))
      .toMatchObject({ status: "Fullført", activity: "20 av 20 moduler kontrollert · 3 funn", bar: null });
    expect(describeJob(job({ status: "failed", error: "Mistet forbindelsen til Canvas." })))
      .toMatchObject({ status: "Feilet", state: "failed", activity: "Mistet forbindelsen til Canvas.", bar: null });
    expect(describeJob(job({ status: "interrupted", error: null })))
      .toMatchObject({ status: "Avbrutt", state: "interrupted", activity: "EmneKlar ble avsluttet mens jobben kjørte." });
    expect(describeJob(job({ status: "cancelled", progress: progress({ types: { module: { label: "Moduler", total: 20, done: 7, failed: 0 } } }) })).activity)
      .toBe("Du avbrøt jobben etter 7 av 20 moduler.");
  });

  it("a finished analysis that found broken links is still «Fullført»; elements that could not be checked are counted", () => {
    const d = describeJob(job({ status: "completed", result: { status: "partial" }, progress: progress({
      types: { link: { label: "Lenker", total: 10, done: 10, failed: 2 } }, findings: { "content_quality:violation": 5 } }) }));
    expect(d.status).toBe("Fullført");
    expect(d.activity).toBe("8 av 10 lenker kontrollert · 2 kunne ikke kontrolleres · 5 funn");
    expect(d.note).toMatch(/begrensningene/);
  });
});

describe("names, counts and the summary", () => {
  it("names an analysis by its area", () => {
    expect(jobName(job())).toBe("Innholdskvalitet");
    expect(jobName(job({ params: { domains: ["accessibility"], scope: "items" } }))).toBe("Universell utforming – valgte elementer");
    expect(jobName(job({ params: { domains: ["accessibility", "structure"] } }))).toBe("Analyse av hele emnet");
    expect(jobName(job({ kind: "quiz_review", title: "Kvalitetssjekk av quiz" }))).toBe("Kvalitetssjekk av quiz");
  });

  it("keeps capitals in units like «KI-forespørsler»", () => {
    expect(jobCounts(progress({ types: { ai: { label: "KI-forespørsler", total: 3, done: 1, failed: 0 } } }))?.unit).toBe("KI-forespørsler");
  });

  it("«2 pågår · 1 avbrutt»: errors are «feilet»/«avbrutt», never «avvik»", () => {
    const jobs = [job({ id: "a" }), job({ id: "b", status: "pausing" }), job({ id: "c", status: "interrupted" }),
      job({ id: "d", status: "failed" }), job({ id: "f", status: "queued" })];
    expect(summaryText(summarizeJobs(jobs))).toBe("2 pågår · 1 venter · 1 feilet · 1 avbrutt");
    expect(summaryText(summarizeJobs([job({ status: "completed" })]))).toBe("");
  });

  it("the newest snapshot wins, and a stopped job never goes back to running", () => {
    const stopped = job({ status: "completed", progress: progress({ version: 5 }) });
    expect(newerJob(stopped, job({ progress: progress({ version: 9 }) }))).toBe(stopped);
    const old = job({ progress: progress({ version: 3 }) });
    expect(newerJob(job({ progress: progress({ version: 4 }) }), old).progress.version).toBe(4);
    expect(newerJob(old, job({ status: "paused", progress: progress({ version: 3 }) })).status).toBe("paused");
  });
});

describe("retry and freshness", () => {
  it("only a stopped analysis is started again from the panel, with the same choices", () => {
    const failed = job({ status: "failed", params: { domains: ["accessibility"], scope: "modules", module_ids: ["7"] } });
    expect(retryRequest(failed)).toEqual({ course_id: "101", scope: "modules", domains: ["accessibility"], module_ids: ["7"], items: [] });
    expect(retryRequest(job({ status: "completed" }))).toBeNull();
    expect(retryRequest(job({ status: "running" }))).toBeNull();
    expect(retryRequest(job({ kind: "apply_changes", status: "failed" })), "a job that writes to Canvas is never retried from here").toBeNull();
  });

  it("keeps the time of the results shown while a new check runs, and says when it did not finish", () => {
    const at = "2026-11-06T14:42:00Z";
    expect(freshnessText({ resultsAt: at, running: true })).toMatch(/^Viser resultater fra 6\. november( 2026)? kl\. \d{2}\.42\. Ny kontroll pågår\.$/);
    expect(freshnessText({ resultsAt: null, running: true })).toBe("Første kontroll pågår.");
    expect(freshnessText({ resultsAt: at, running: false, stopped: job({ status: "failed" }) }))
      .toMatch(/^Den nye kontrollen ble ikke fullført\. Viser resultater fra 6\. november( 2026)? kl/);
    expect(freshnessText({ resultsAt: at, running: false, stopped: job({ status: "cancelled" }) })).toMatch(/^Den nye kontrollen ble avbrutt\./);
    expect(freshnessText({ resultsAt: at, running: false })).toBeNull();
  });
});

describe("the compact overview", () => {
  const NOW = Date.parse("2026-11-10T12:00:00Z");
  const at = (hoursAgo: number) => new Date(NOW - hoursAgo * 3_600_000).toISOString();
  const done = (id: string, hoursAgo: number, over: Partial<Job> = {}) => job({
    id, status: "completed", created_at: at(hoursAgo + 0.1), finished_at: at(hoursAgo),
    params: { domains: ["structure"], scope: "modules", module_ids: [id] }, ...over });
  const compact = (jobs: Job[], over: Partial<Parameters<typeof compactJobs>[1]> = {}) =>
    compactJobs(jobs, { hidden: new Set(), now: NOW, ...over });

  it("one logical job per course, kind and scope – not by title or time; module order does not matter", () => {
    const a = job({ params: { domains: ["structure", "accessibility"], scope: "modules", module_ids: ["1", "2"] } });
    const b = job({ id: "b", title: "Et annet navn", created_at: at(5),
      params: { scope: "modules", module_ids: ["2", "1"], domains: ["accessibility", "structure"] } });
    expect(logicalKey(a)).toBe(logicalKey(b));
    expect(logicalKey(job({ params: { ...a.params, module_ids: ["3"] } }))).not.toBe(logicalKey(a));
    expect(logicalKey(job({ course_id: "202", params: a.params }))).not.toBe(logicalKey(a));
  });

  it("shows at most four finished jobs, only from the last day; both limits apply", () => {
    const jobs = [done("1", 1), done("2", 2), done("3", 3), done("4", 4), done("5", 5), done("old", 30)];
    const result = compact(jobs);
    expect(result.rows.map((j) => j.id)).toEqual(["1", "2", "3", "4"]);
    expect(RECENT_FINISHED).toBe(4);
    expect(compact([done("old", 30)]).rows).toEqual([]);
  });

  it("«Fjern fullførte» leaves out what finished before it – later ones show again", () => {
    const jobs = [done("1", 1), done("2", 3)];
    expect(compact(jobs, { clearedAt: Date.parse(at(2)) }).rows.map((j) => j.id)).toEqual(["1"]);
  });

  it("keeps unresolved jobs however old, until hidden or replaced by a new attempt", () => {
    const failed = job({ id: "f", status: "failed", created_at: at(24 * 30), finished_at: at(24 * 30) });
    expect(compact([failed]).rows.map((j) => j.id)).toEqual(["f"]);
    expect(compact([failed]).summary.failed).toBe(1);
    expect(compact([failed], { hidden: new Set(["f"]) }).rows).toEqual([]);
    const retried = job({ id: "r", created_at: at(0) });
    const result = compact([failed, retried]);
    expect(result.rows.map((j) => j.id), "the new attempt takes the row").toEqual(["r"]);
    expect(result.summary).toMatchObject({ running: 1, failed: 0 });
  });

  it("never hides an active job, also when a newer run has the same logical key", () => {
    const older = job({ id: "old", created_at: at(1) });
    const newer = job({ id: "new", status: "queued", created_at: at(0) });
    expect(compact([older, newer]).rows.map((j) => j.id).sort()).toEqual(["new", "old"]);
  });

  it("the same job twice (an update and the history) is one row", () => {
    const one = done("1", 1, { kind: "video_scan", title: "Standardiser videoavspillere", params: {} });
    expect(compact([one, { ...one }]).rows).toHaveLength(1);
  });

  it("caps the list at ten rows: active and unresolved first, the rest of the room to finished ones", () => {
    const failed = Array.from({ length: 12 }, (_, i) => job({ id: `f${i}`, status: "failed", finished_at: at(i + 1),
      params: { domains: ["accessibility"], scope: "items", items: [{ object_type: "page", object_id: String(i) }] } }));
    const result = compact([...failed, done("d", 1)]);
    expect(result.rows).toHaveLength(10);
    expect(result.overflow).toBe(2);
    expect(result.summary.failed, "the header counts every unresolved job").toBe(12);
    expect(result.rows.some((j) => j.id === "d"), "no room for finished ones").toBe(false);
    expect(compact([...failed, done("d", 1)], { showAll: true }).rows).toHaveLength(12);
    const few = compact([...failed.slice(0, 7), done("d1", 1), done("d2", 2), done("d3", 3), done("d4", 4)]);
    expect(few.rows.map((j) => j.id).slice(7)).toEqual(["d1", "d2", "d3"]);
    expect(few.overflow).toBe(0);
  });
});

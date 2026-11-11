// What the overview shows, computed from the overview API: the figures per area (each finding has exactly one class, so
// the figures never overlap), what the highlighted figures leave out, and which analysis each area comes from.
import { formatShortDate, formatShortWhen, formatWhen, formatNumber } from "../../core/format";
import type { ActivityStatusTone, Tone } from "../../design-system";
import { ACTION } from "../changes/history";

export type DomainKey = "accessibility" | "content_quality" | "structure" | "quiz";

export interface RunInfo {
  id: number;
  scope_type: string;
  status: string;
  time: string | null;
  /** The areas the run analysed (a full analysis of one area is not a full analysis of every area). */
  domains?: string[];
}

export interface DomainCard {
  domain: string;
  analyzed: boolean;
  last_run: string | null;
  run_id: number | null;
  /** Every analysis that contributed, newest first (more than one: the area combines analyses). */
  runs: RunInfo[];
  total: number;
  by_classification: Record<string, number>;
  by_rule: Record<string, number>;
  by_category: Record<string, number>;
  violations_high: number;
  likely_high: number;
  objects: number;
  /** Quiz: with the AI review, as the Quizassistent page counts «åpne funn». */
  total_with_ai?: number;
  /** Content quality: addresses that do not work – the «Fungerer ikke» total in Innholdskvalitet → Lenker. */
  dead_links?: number;
  /** Quiz: the distinct quizzes the findings are in, and the distinct questions they are about. */
  quizzes_affected?: number;
  questions_affected?: number;
}

export interface Step {
  key: string;
  title: string;
  description: string;
  action: string;
  path: string | null;
  tone: Tone;
  count: number;
}

export interface ActivityItem {
  type: "analysis" | "job" | "change";
  time: string | null;
  title: string;
  detail: string | null;
  status: string;
  summary?: string | null;
}

export interface Overview {
  cards: Record<DomainKey, DomainCard>;
  /** The newest analysis – the time shown once at the top. */
  analysis: RunInfo | null;
  /** The newest analysis of the whole course (any areas) – told apart from a later partial analysis. */
  full_analysis?: RunInfo | null;
  /** Most important first. */
  next_steps: Step[];
  activity: ActivityItem[];
  stats: (Record<string, number | string> & { run_id: number; analysed_at: string | null }) | null;
  pending_changes: number;
}

export const SCOPE: Record<string, string> = { course: "hele emnet", modules: "valgte moduler", items: "valgte elementer" };
export const CQ_DEAD = ["CQ-LINK-DEAD", "CQ-LINK-INTERNAL-MISSING"];
export const CQ_MEDIA = ["CQ-MEDIA-UNAVAILABLE"];

const n = formatNumber;

export const count = (card: DomainCard, ...classes: string[]) =>
  classes.reduce((sum, c) => sum + (card.by_classification[c] ?? 0), 0);
export const ruleCount = (card: DomainCard, ...rules: string[]) => rules.reduce((sum, r) => sum + (card.by_rule[r] ?? 0), 0);

/** «a, b og c» */
export function and(parts: string[]): string {
  return parts.length <= 1 ? parts.join("") : `${parts.slice(0, -1).join(", ")} og ${parts[parts.length - 1]}`;
}

const AREA_NAME: Record<string, string> = {
  accessibility: "universell utforming", content_quality: "innholdskvalitet", structure: "emnestruktur", quiz: "quiz",
};

/** «alle områder», or the areas by name: «universell utforming og innholdskvalitet». */
export function areaNames(domains: string[] | undefined, quizEnabled = true): string {
  const all = ["accessibility", "content_quality", "structure", ...(quizEnabled ? ["quiz"] : [])];
  const ran = (domains ?? []).filter((d) => d in AREA_NAME);
  if (ran.length && all.every((d) => ran.includes(d))) return "alle områder";
  return and(ran.map((d) => AREA_NAME[d]));
}

/**
 * The line at the top: what the newest analysis covered, and – after a partial one – when the whole course was last
 * analysed. Says so when some areas still come from older analyses. Only times and coverage the data has.
 *   «Siste delanalyse: 10. nov. kl. 14.53 (valgte moduler, universell utforming). Hele emnet sist analysert
 *    6. nov. kl. 15.42 (alle områder).»
 *   «Sist analysert 6. nov. kl. 15.42: hele emnet, innholdskvalitet. Bygger også på eldre analyser.»
 */
export function analysisLine(analysis: RunInfo | null, { full = null, cards = [], quizEnabled = true }: {
  full?: RunInfo | null;
  cards?: DomainCard[];
  quizEnabled?: boolean;
} = {}): string | undefined {
  if (!analysis?.time) return undefined;
  const areas = areaNames(analysis.domains, quizEnabled);
  if (analysis.scope_type !== "course") {
    const scope = SCOPE[analysis.scope_type] ?? "deler av emnet";
    const first = `Siste delanalyse: ${formatShortWhen(analysis.time)} (${scope}${areas ? `, ${areas}` : ""}).`;
    const second = full?.time
      ? `Hele emnet sist analysert ${formatShortWhen(full.time)}${full.domains?.length ? ` (${areaNames(full.domains, quizEnabled)})` : ""}.`
      : "Hele emnet er ikke analysert ennå.";
    return `${first} ${second}`;
  }
  const older = cards.some((card) => card.analyzed && (card.runs.length > 1 || card.run_id !== analysis.id));
  return `Sist analysert ${formatShortWhen(analysis.time)}: hele emnet${areas ? `, ${areas}` : ""}.${older ? " Bygger også på eldre analyser." : ""}`;
}

/** The short coverage and age of one area's results, for the card: «Hele emnet · 6. nov. kl. 15.42», «Delanalyse
 *  (valgte moduler) · 10. nov. kl. 14.53», or «Satt sammen av 3 analyser · nyeste 10. nov.». */
export function coverageLine(card: DomainCard): string | null {
  if (!card.analyzed || !card.last_run) return null;
  if (card.runs.length > 1) return `Satt sammen av ${card.runs.length} analyser · nyeste ${formatShortDate(card.last_run)}`;
  const run = card.runs[0];
  const when = formatShortWhen(card.last_run);
  return run && run.scope_type !== "course" ? `Delanalyse (${SCOPE[run.scope_type] ?? "deler av emnet"}) · ${when}` : `Hele emnet · ${when}`;
}

/** Behind «Vis detaljer»: which analyses an area combines (the newest analysis of each content item wins). */
export function coverageDetails(card: DomainCard): string | null {
  if (!card.analyzed || card.runs.length <= 1) return null;
  const runs = card.runs.map((run) => `${formatWhen(run.time)} (${SCOPE[run.scope_type] ?? "deler av emnet"})`);
  return `Resultatene er satt sammen av ${card.runs.length} analyser – for hvert innholdselement gjelder den nyeste: ${and(runs)}.`;
}

/** «I tillegg 12 bør vurderes, 6 til manuell kontroll og 1 forbedringsforslag» – the classes not shown as figures. */
export function accessibilityRest(card: DomainCard): string | null {
  const review = count(card, "should_review");
  const manual = count(card, "manual_check");
  const improvement = count(card, "improvement");
  const parts = [
    review ? `${n(review)} bør vurderes` : null,
    manual ? `${n(manual)} til manuell kontroll` : null,
    improvement ? `${n(improvement)} forbedringsforslag` : null,
  ].filter((p): p is string => Boolean(p));
  return parts.length ? `I tillegg ${and(parts)}` : null;
}

/** What the content quality total contains besides the dead links and unavailable videos shown as figures. */
export function contentQualityRest(card: DomainCard): string | null {
  const dead = ruleCount(card, ...CQ_DEAD);
  const media = ruleCount(card, ...CQ_MEDIA);
  const cat = (key: string) => card.by_category[key] ?? 0;
  const known = cat("links") + cat("media") + cat("html") + cat("content");
  const parts = [
    cat("links") - dead > 0 ? `${n(cat("links") - dead)} andre lenkeproblemer` : null,
    cat("media") - media > 0 ? `${n(cat("media") - media)} om annen video og innebygd innhold` : null,
    cat("html") ? `${n(cat("html"))} om HTML og kode` : null,
    cat("content") ? `${n(cat("content"))} om innhold` : null,
    card.total - known > 0 ? `${n(card.total - known)} annet` : null,
  ].filter((p): p is string => Boolean(p));
  return parts.length ? `Resten: ${and(parts)}` : null;
}

/** Structure: «bør vurderes» and «forbedringsforslag» are separate classes; the total is all suggestions. */
export function structureRest(card: DomainCard): string | null {
  const others = card.total - count(card, "should_review", "improvement");
  return others > 0 ? `og ${n(others)} andre` : null;
}

export function total(value: number, one: string, many: string): string {
  return `${n(value)} ${value === 1 ? one : many}`;
}

/* ------------------------------------------------------------------ activity status (presentation only) */

/** Which status mark an activity gets: «kind» picks the icon, «tone» the colour (the --status-* tokens). */
export interface ActivityStatus {
  kind: "completed" | "failed" | "stopped" | "running" | "waiting" | "conflict" | "undone" | "not_sent" | "other";
  label: string;
  tone: ActivityStatusTone;
}

/** Analyses and other jobs, by the status the job manager records (nothing is recalculated here). «Avbrutt» (stopped)
 * and «Feilet» stay apart. */
const JOB_STATUS: Record<string, ActivityStatus> = {
  completed: { kind: "completed", label: "Fullført", tone: "success" },
  failed: { kind: "failed", label: "Feilet", tone: "danger" },
  cancelled: { kind: "stopped", label: "Avbrutt", tone: "warning" },
  interrupted: { kind: "stopped", label: "Avbrutt", tone: "warning" },
  running: { kind: "running", label: "Pågår", tone: "info" },
  queued: { kind: "waiting", label: "Venter", tone: "neutral" },
  paused: { kind: "waiting", label: "Satt på pause", tone: "neutral" },
};

/** Published changes, by the change log's action – the same labels as the change log itself. */
const CHANGE_KIND: Record<string, ActivityStatus["kind"]> = {
  apply: "completed", failed: "failed", conflict: "conflict", undo: "undone", dry_run: "not_sent",
};

export function activityStatus(item: ActivityItem): ActivityStatus {
  if (item.type === "change") {
    const action = ACTION[item.status as keyof typeof ACTION];
    if (!action) return { kind: "other", label: item.status, tone: "neutral" };
    const tone: ActivityStatusTone = action.tone === "danger" || action.tone === "warning" || action.tone === "success" ||
      action.tone === "info" ? action.tone : "neutral";
    return { kind: CHANGE_KIND[item.status] ?? "other", label: action.label, tone };
  }
  return JOB_STATUS[item.status] ?? { kind: "other", label: item.detail ?? item.status, tone: "neutral" };
}

/** The line under the title, without repeating the status the mark already states (read once by screen readers). */
export function activityMeta(item: ActivityItem): string | null {
  if (item.type === "change") return item.summary || null;
  if (item.status === "interrupted") return "EmneKlar ble avsluttet underveis";
  const status = JOB_STATUS[item.status];
  if (!status) return null; // an unknown status: the mark already shows the API's own text
  return item.detail && item.detail !== status.label ? item.detail : null;
}

/** The quiz card's secondary figures: the quizzes the findings are in and the questions they are about – counts from the
 *  overview API, nothing recalculated here. Without the split (an older server) the existing total of affected
 *  questions and quizzes is described as exactly that. */
export function quizAffected(card: DomainCard): { value: number; label: string }[] {
  if (card.quizzes_affected === undefined || card.questions_affected === undefined) {
    return [{ value: card.objects, label: card.objects === 1 ? "spørsmål eller quiz med funn" : "spørsmål og quizer med funn" }];
  }
  return [
    { value: card.quizzes_affected, label: card.quizzes_affected === 1 ? "quiz med funn" : "quizer med funn" },
    { value: card.questions_affected, label: card.questions_affected === 1 ? "spørsmål med funn" : "spørsmål med funn" },
  ];
}

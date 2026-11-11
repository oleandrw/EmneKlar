// The analysis side of the shared job status: the one analysis button in the header (it follows the page), and the
// line that says when the results on a page are from. Both read the same job status as «Analysestatus», so the
// activity and the numbers always agree with the panel.
import { Play } from "lucide-react";
import { useLocation } from "react-router";

import type { Job } from "../../core/api/types";
import { useCourseAnalysis, useJobs } from "../../core/jobs";
import { describeJob, freshnessText, isActive, jobCounts, jobName } from "../../core/jobs-model";
import type { AnalysisDomain } from "../../core/labels";
import { useSession } from "../../core/session";
import { useUi } from "../../core/ui";
import { Button, cx } from "../../design-system";

export interface PageAnalysis {
  path: string;
  label: string;
  /** The area the page analyses; none on Oversikt (the whole course, every area chosen in the dialog). */
  area?: AnalysisDomain;
  /** Only when this feature is switched on. */
  flag?: string;
}

/** The pages that have an analysis of their own. Other pages show no analysis button – nothing is made up. */
export const PAGE_ANALYSES: PageAnalysis[] = [
  { path: "/oversikt", label: "Analyser hele emnet" },
  { path: "/universell-utforming", label: "Analyser universell utforming", area: "accessibility" },
  { path: "/innholdskvalitet", label: "Analyser innholdskvalitet", area: "content_quality" },
  { path: "/emnestruktur", label: "Analyser emnestruktur", area: "structure" },
  { path: "/quizassistent", label: "Analyser quizkvalitet", area: "quiz", flag: "quiz_assistant" },
];

export function pageAnalysis(pathname: string, flags: Record<string, boolean> = {}): PageAnalysis | null {
  return PAGE_ANALYSES.find((page) => (pathname === page.path || pathname.startsWith(`${page.path}/`))
    && (!page.flag || flags[page.flag] !== false)) ?? null;
}

/** The header button's text for an area: «Analyser innholdskvalitet» – for texts that point to it. */
export function analysisLabelFor(area: AnalysisDomain): string {
  return PAGE_ANALYSES.find((page) => page.area === area)?.label ?? "Analyser hele emnet";
}

/** «Analyserer innholdet · 124 av 380» – the status of a running job, for a button or a line of text. */
export function jobButtonText(job: Job): string {
  return describeJob(job).button;
}

/** The status in the header button: the full text, and a short one for narrow screens («124 av 380», «Henter …»). */
export function analysisButtonStatus(job: Job, area: AnalysisDomain | undefined, stale: boolean): { full: string; short: string } {
  if (stale) return { full: "Ingen kontakt – status ukjent", short: "Status ukjent" };
  const d = describeJob(job);
  const counts = d.bar?.kind === "known" ? jobCounts(job.progress) : null;
  const count = counts ? `${counts.done} av ${counts.total}` : null;
  const short = count ?? `${d.button.split(" ")[0]} …`;
  const covers = !area || ((job.params?.domains ?? []) as string[]).includes(area);
  // Another area of the same course is being analysed: EmneKlar runs one analysis per course at a time.
  if (!covers) return { full: `${jobName(job)} pågår${count ? ` · ${count}` : ""}`, short };
  return { full: d.button, short };
}

/**
 * The one analysis button, at the top right. Its text and action follow the page: «Analyser hele emnet» on Oversikt,
 * «Analyser innholdskvalitet» on Innholdskvalitet, and so on – never a full analysis from a page for one area. Pages
 * without an analysis of their own have no button. While an analysis of the course runs, the button is disabled and
 * shows what it does now (no animation) – from the same job status as the panel. It stays focusable (aria-disabled),
 * so focus is not lost when the analysis dialog closes.
 */
export function HeaderAnalysisButton() {
  const { pathname } = useLocation();
  const session = useSession();
  const ui = useUi();
  const { stale } = useJobs();
  const { running, courseId } = useCourseAnalysis();
  const page = pageAnalysis(pathname, session.flags);
  if (!page) return null;
  if (running) {
    const { full, short } = analysisButtonStatus(running, page.area, stale);
    return (
      <Button variant="secondary" size="lg" className="ek-header__analyse ek-btn--status" aria-disabled="true"
        aria-label={`${stale ? "Analyse" : "Analyse pågår"}: ${full}`} title={full}
        onClick={(event) => event.preventDefault()}>
        <span className="ek-analyse-status__full">{full}</span>
        <span className="ek-analyse-status__short" aria-hidden="true">{short}</span>
      </Button>
    );
  }
  return (
    <Button variant="primary" size="lg" className="ek-header__analyse" icon={<Play aria-hidden="true" />}
      onClick={() => ui.openAnalysis(page.area ? { area: page.area } : undefined)} disabled={!courseId}
      title={courseId ? undefined : "Velg et emne først"} aria-haspopup="dialog" aria-label={page.label}>
      {/* «Analyser» on narrow screens; the name is always the full text. */}
      <span className="ek-analyse-label__full">{page.label}</span>
      <span className="ek-analyse-label__short" aria-hidden="true">Analyser</span>
    </Button>
  );
}

/** What a newer check did to the results shown, or null when nothing is going on. */
export function useResultsFreshness(domain: AnalysisDomain | undefined, resultsAt: string | null | undefined): string | null {
  const { runningHere, latest } = useCourseAnalysis(domain);
  const { stale } = useJobs();
  const after = (job: Job) => !resultsAt || Date.parse(job.created_at) > Date.parse(resultsAt);
  const stopped = latest && !isActive(latest) && latest.status !== "completed" && after(latest) ? latest : null;
  return freshnessText({ resultsAt, running: Boolean(runningHere), stopped, stale });
}

/** «Viser resultater fra 6. november kl. 15.42. Ny kontroll pågår.» – a quiet line, not a status card. */
export function ResultsFreshness({ domain, resultsAt, className }: {
  domain?: AnalysisDomain;
  resultsAt: string | null | undefined;
  className?: string;
}) {
  const text = useResultsFreshness(domain, resultsAt);
  if (!text) return null;
  return <p className={cx("ek-freshness", className)}>{text}</p>;
}

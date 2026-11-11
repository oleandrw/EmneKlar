// «Analysestatus»: a compact control just left of the analysis button, and a panel below it.
//
// * At rest the control is a discreet icon («Analysestatus» as tooltip and name). Otherwise it says what is going on –
//   «1 pågår», «1 feilet», «2 pågår · 1 avbrutt» – and counts every active and unresolved job, also those that do not
//   fit in the short list. It holds the only spinning indicator in EmneKlar's job status, and only while the panel is
//   closed (the bars in the panel show the activity). Unresolved jobs get a static warning symbol.
// * A disclosure (aria-expanded/aria-controls), not a modal: the page stays usable. Escape closes it and returns focus
//   to the control (when focus was in it); a click outside closes it. Opening by itself (a job was just started)
//   never moves focus.
// * The panel is an overview of current jobs, not a history: running and waiting jobs, unresolved ones (until hidden or
//   replaced by a new attempt), and at most four finished ones from the last day. At most ten rows. The full history
//   is under Rapporter.
import { useMutation } from "@tanstack/react-query";
import {
  Activity,
  Ban,
  Check,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  CircleDashed,
  Clock,
  Pause,
  TriangleAlert,
  WifiOff,
} from "lucide-react";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router";

import { Alert, Button, ButtonLink, ConfirmDialog, IconButton, ProgressBar } from "../../design-system";
import { jobAction } from "../../features/analysis/useJob";
import type { Job } from "../api/types";
import { courseLabel, useCourses, useCurrentCourse } from "../course";
import { formatWhenShort } from "../format";
import { useJobs } from "../jobs";
import {
  compactJobs,
  describeJob,
  isActive,
  isProblem,
  JOB_PLACE,
  jobName,
  logicalKey,
  retryRequest,
  summaryText,
  type JobDescription,
} from "../jobs-model";
import { useSession } from "../session";
import { useUi } from "../ui";

const PANEL_MAX = 400;
const GUTTER = 16;
/** The last-day rule for finished jobs is applied again at this pace (and every time the panel opens). */
const TIDY_MS = 60_000;

const BADGE_TONE: Record<JobDescription["state"], string> = {
  running: "info",
  stopping: "info",
  paused: "neutral",
  waiting: "neutral",
  completed: "success",
  failed: "danger",
  interrupted: "warning",
  cancelled: "warning",
};

/** A static symbol per state – the job rows never spin. */
function StateIcon({ state, stale }: { state: JobDescription["state"]; stale: boolean }) {
  if (stale && (state === "running" || state === "stopping")) return <WifiOff aria-hidden="true" />;
  switch (state) {
    case "running":
    case "stopping":
      return <CircleDashed aria-hidden="true" />;
    case "waiting":
      return <Clock aria-hidden="true" />;
    case "paused":
      return <Pause aria-hidden="true" />;
    case "completed":
      return <Check aria-hidden="true" />;
    case "cancelled":
      return <Ban aria-hidden="true" />;
    default:
      return <CircleAlert aria-hidden="true" />;
  }
}

function JobRow({ job, stale, course, onCancel }: {
  job: Job;
  stale: boolean;
  course: string | null;
  onCancel: (job: Job) => void;
}) {
  const ui = useUi();
  const { hide, retry, setPanelOpen } = useJobs();
  const d = describeJob(job);
  const name = jobName(job);
  const active = isActive(job);
  const unknown = stale && active;
  const state = unknown ? "unknown" : d.state;
  const control = useMutation({ mutationFn: (kind: "pause" | "resume") => jobAction(job.id, kind) });
  const again = useMutation({ mutationFn: () => retry(job) });
  const canRetry = Boolean(retryRequest(job));
  const place = JOB_PLACE[job.kind];
  const stopped = isProblem(job);
  const statusText = unknown ? "Ukjent status" : d.status;

  return (
    <li className="ek-job" data-state={state}>
      <span className="ek-job__tile"><StateIcon state={d.state} stale={stale} /></span>
      <div className="ek-job__body">
        <div className="ek-job__top">
          <span className="ek-job__name">{name}</span>
          <span className="ek-job__badge" data-tone={unknown ? "warning" : BADGE_TONE[d.state]}>{statusText}</span>
        </div>
        {course ? <span className="ek-job__course">{course}</span> : null}
        <p className="ek-job__activity">
          {unknown ? "Sist kjente aktivitet: " : null}
          {d.step && active ? <span className="ek-job__step">{d.step}: </span> : null}
          {d.activity}
        </p>
        {d.bar && !unknown ? (
          d.bar.kind === "known" ? (
            <>
              <ProgressBar size="sm" tone="info" value={d.bar.percent} label={`Fremdrift: ${name}`}
                valueText={`${d.bar.counts}, ${d.bar.percent} prosent`} />
              <p className="ek-job__meta">
                <span>{d.bar.counts}</span>
                <span>{d.bar.percent} %</span>
              </p>
            </>
          ) : (
            <>
              <ProgressBar size="sm" tone="info" value={null} label={`Fremdrift: ${name}`} valueText={d.bar.detail} />
              <p className="ek-job__meta"><span>{d.bar.detail}</span></p>
            </>
          )
        ) : null}
        {d.note && !unknown ? <p className="ek-job__note">{d.note}</p> : null}
        {!active && job.finished_at ? <p className="ek-job__note">{d.status} {formatWhenShort(job.finished_at)}</p> : null}
        {again.error ? <Alert tone="danger" role="alert">{(again.error as Error).message}</Alert> : null}
        {control.error ? <Alert tone="danger" role="alert">{(control.error as Error).message}</Alert> : null}
        <div className="ek-job__actions">
          {active && !unknown && job.supports_pause && job.status === "running" ? (
            <Button size="sm" variant="ghost" loading={control.isPending} onClick={() => control.mutate("pause")}>
              Pause<span className="ek-visually-hidden">: {name}</span>
            </Button>
          ) : null}
          {active && !unknown && job.supports_pause && (job.status === "paused" || job.status === "pausing") ? (
            <Button size="sm" variant="ghost" loading={control.isPending} onClick={() => control.mutate("resume")}>
              Fortsett<span className="ek-visually-hidden">: {name}</span>
            </Button>
          ) : null}
          {active && !unknown && job.status !== "cancelling" ? (
            <Button size="sm" variant="ghost" onClick={() => onCancel(job)}>
              Avbryt<span className="ek-visually-hidden">: {name}</span>
            </Button>
          ) : null}
          {active && job.kind === "analysis" && job.progress?.types ? (
            <Button size="sm" variant="ghost" aria-haspopup="dialog" onClick={() => {
              setPanelOpen(false);
              ui.watchJob(job.id);
              ui.openAnalysis();
            }}>
              Detaljer<span className="ek-visually-hidden">: {name}</span>
            </Button>
          ) : null}
          {stopped && canRetry ? (
            <Button size="sm" variant="secondary" loading={again.isPending} onClick={() => again.mutate()}>
              Prøv igjen<span className="ek-visually-hidden">: {name}</span>
            </Button>
          ) : null}
          {stopped && !canRetry && job.kind === "apply_changes" ? (
            <Button size="sm" variant="secondary" aria-haspopup="dialog" onClick={() => {
              setPanelOpen(false);
              ui.openChanges();
            }}>
              Åpne endringskøen
            </Button>
          ) : null}
          {stopped && !canRetry && place ? (
            <ButtonLink size="sm" variant="secondary" to={place.to} onClick={() => setPanelOpen(false)}>
              {place.label}
            </ButtonLink>
          ) : null}
          {stopped ? (
            <Button size="sm" variant="ghost" onClick={() => hide([job.id])}>
              Skjul<span className="ek-visually-hidden">: {name}</span>
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  );
}

/** Where the panel goes: under the control, right-aligned with the header's buttons, always inside the window. */
function usePanelPosition(open: boolean, buttonRef: React.RefObject<HTMLButtonElement | null>) {
  const [style, setStyle] = useState<CSSProperties>({});
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const button = buttonRef.current;
      const rect = button?.getBoundingClientRect();
      if (!button || !rect) return;
      const edge = button.closest(".ek-header__group")?.getBoundingClientRect().right ?? rect.right;
      const viewport = document.documentElement.clientWidth || window.innerWidth;
      const width = Math.min(PANEL_MAX, viewport - 2 * GUTTER);
      const right = Math.min(Math.max(GUTTER, viewport - Math.max(edge, rect.right)), viewport - GUTTER - width);
      const top = rect.bottom + 8;
      setStyle({ top, right, width, maxHeight: `calc(100dvh - ${Math.round(top) + GUTTER}px)` });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, buttonRef]);
  return style;
}

export function JobStatus() {
  const session = useSession();
  const { jobs, hidden, clearedAt, clearFinished, panelOpen: open, setPanelOpen, stale, updatedAt, loaded, focusRequest } =
    useJobs();
  const { courseId } = useCurrentCourse();
  const courses = useCourses(session.canvas.token_configured);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const panelId = useId();
  const headingId = useId();
  const finishedId = useId();
  const style = usePanelPosition(open, buttonRef);
  const [cancelling, setCancelling] = useState<Job | null>(null);
  const [showAll, setShowAll] = useState(false);
  const cancel = useMutation({ mutationFn: (job: Job) => jobAction(job.id, "cancel") });

  // Tidy by itself: the last-day rule is applied again now and then and whenever the panel opens.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const handle = window.setInterval(() => setNow(Date.now()), TIDY_MS);
    return () => window.clearInterval(handle);
  }, []);
  useEffect(() => {
    if (open) setNow(Date.now());
    else setShowAll(false);
  }, [open]);

  const compact = useMemo(() => compactJobs(jobs, { hidden, clearedAt, now, showAll }), [jobs, hidden, clearedAt, now, showAll]);
  const { summary } = compact;
  // Running, waiting and unresolved jobs first; the last completed ones under «Sist fullførte».
  const currentRows = compact.rows.slice(0, compact.rows.length - compact.finished.length);
  const rowKeys = useMemo(() => {
    const count = new Map<string, number>();
    for (const job of compact.rows) count.set(logicalKey(job), (count.get(logicalKey(job)) ?? 0) + 1);
    return new Map(compact.rows.map((job) => [job.id, (count.get(logicalKey(job)) ?? 0) > 1 ? job.id : logicalKey(job)]));
  }, [compact.rows]);
  const running = summary.running > 0;
  const unresolved = summary.failed + summary.interrupted;

  // «Vis i Analysestatus» from a page moves focus to the panel (opening it by itself never does).
  useEffect(() => {
    if (focusRequest > 0) window.setTimeout(() => headingRef.current?.focus(), 0);
  }, [focusRequest]);

  // Click outside and Escape close the panel.
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Element | null;
      if (wrapperRef.current?.contains(target) || target?.closest?.("dialog[open]")) return;
      setPanelOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const focused = document.activeElement;
      if (focused?.closest("dialog[open]")) return; // a dialog closes itself first
      const inside = Boolean(wrapperRef.current?.contains(focused));
      if (!inside && document.querySelector("dialog[open]")) return;
      setPanelOpen(false);
      if (inside) buttonRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, setPanelOpen]);

  // Jobs for several courses: name the course on every row, so they are not mixed up.
  const manyCourses = new Set(compact.rows.map((j) => j.course_id).filter(Boolean)).size > 1;
  const rowCourse = (job: Job) => {
    if (!job.course_id || (job.course_id === courseId && !manyCourses)) return null;
    const course = courses.data?.courses.find((c) => c.id === job.course_id);
    const label = course ? `Emne: ${courseLabel(course)}` : `Emne-ID ${job.course_id}`;
    return job.course_id === courseId ? `${label} (valgt)` : label;
  };

  // At rest – nothing running or waiting and nothing unresolved – the control is a discreet icon. Otherwise it says
  // what is going on: «1 pågår», «1 feilet», «2 pågår · 1 avbrutt».
  const resting = !stale && summaryText(summary) === "";
  const text = stale ? "Ingen kontakt" : summaryText(summary);
  const label = resting ? "Analysestatus" : `${text} – analysestatus`;
  // The one spinning indicator – only while something runs and the panel is closed (static under reduced motion).
  // Unresolved jobs get a static warning symbol, never an animation.
  const icon = stale ? <WifiOff aria-hidden="true" />
    : running && !open ? (
      <>
        <span className="ek-spinner ek-jobs-spinner" aria-hidden="true" />
        <CircleDashed className="ek-jobs-static" aria-hidden="true" />
      </>
    )
    : running ? <CircleDashed aria-hidden="true" />
    : unresolved > 0 ? <TriangleAlert className="ek-jobs-button__warn" aria-hidden="true" />
    : summary.paused + summary.waiting > 0 ? <Clock aria-hidden="true" />
    : <Activity aria-hidden="true" />;

  return (
    <div className="ek-jobs" ref={wrapperRef}>
      <button ref={buttonRef} type="button" className="ek-jobs-button" data-tone={stale ? "warning" : "neutral"}
        data-mode={resting ? "rest" : "active"} aria-expanded={open} aria-controls={panelId} aria-label={label}
        title={resting ? "Analysestatus" : undefined} onClick={() => setPanelOpen(!open)}>
        {icon}
        {unresolved > 0 && running && !stale ? <TriangleAlert className="ek-jobs-button__warn" aria-hidden="true" /> : null}
        {resting ? null : (
          <>
            <span className="ek-jobs-button__text">{text}</span>
            {open ? <ChevronUp className="ek-jobs-button__chevron" aria-hidden="true" />
              : <ChevronDown className="ek-jobs-button__chevron" aria-hidden="true" />}
          </>
        )}
      </button>
      <section id={panelId} className="ek-jobs-panel" aria-labelledby={headingId} hidden={!open} style={style}>
        <div className="ek-jobs-panel__head">
          <h2 id={headingId} ref={headingRef} className="ek-jobs-panel__title" tabIndex={-1}>Analysestatus</h2>
          <IconButton label="Lukk analysestatus" size="sm" onClick={() => {
            setPanelOpen(false);
            buttonRef.current?.focus();
          }}>
            <ChevronUp aria-hidden="true" />
          </IconButton>
        </div>
        {stale ? (
          <Alert tone="warning" title="Mistet kontakten med EmneKlar">
            Statusen under er fra {updatedAt ? formatWhenShort(new Date(updatedAt).toISOString()) : "før bruddet"} og kan
            være utdatert. EmneKlar prøver igjen automatisk.
          </Alert>
        ) : null}
        {!loaded && !stale ? <p className="ek-small ek-muted">Henter status …</p> : null}
        {loaded && summary.running + summary.paused + summary.waiting === 0 ? (
          <p className="ek-jobs-panel__empty">Ingen analyser pågår</p>
        ) : null}
        {currentRows.length ? (
          <ul className="ek-jobs-list">
            {currentRows.map((job) => (
              // The logical job is the row: a new attempt takes over the row of the one it replaces (two active runs of
              // the same logical job keep a row each).
              <JobRow key={rowKeys.get(job.id)} job={job} stale={stale} course={rowCourse(job)} onCancel={setCancelling} />
            ))}
          </ul>
        ) : null}
        {compact.overflow > 0 ? (
          <Button size="sm" variant="secondary" aria-expanded={showAll} onClick={() => setShowAll(!showAll)}>
            {showAll ? "Vis færre" : `Vis alle aktive og uløste (${compact.pinned.length})`}
          </Button>
        ) : null}
        {compact.finished.length ? (
          <div className="ek-jobs-panel__section">
            <h3 id={finishedId} className="ek-jobs-panel__subtitle">Sist fullførte</h3>
            <ul className="ek-jobs-list" aria-labelledby={finishedId}>
              {compact.finished.map((job) => (
                <JobRow key={rowKeys.get(job.id)} job={job} stale={stale} course={rowCourse(job)} onCancel={setCancelling} />
              ))}
            </ul>
          </div>
        ) : null}
        {cancel.error ? <Alert tone="danger" role="alert">{(cancel.error as Error).message}</Alert> : null}
        <div className="ek-jobs-panel__foot">
          {compact.finished.length ? (
            <Button size="sm" variant="link" onClick={clearFinished}>Fjern fullførte</Button>
          ) : null}
          <Link to="/rapporter#jobbhistorikk" onClick={() => setPanelOpen(false)}>Jobbhistorikk</Link>
        </div>
      </section>
      <ConfirmDialog
        open={cancelling !== null}
        onClose={() => setCancelling(null)}
        onConfirm={() => {
          if (cancelling) cancel.mutate(cancelling);
          setCancelling(null);
        }}
        title={cancelling ? `Avbryte «${jobName(cancelling)}»?` : "Avbryte jobben?"}
        confirmLabel="Avbryt jobben"
        cancelLabel="Fortsett jobben"
        danger
      >
        <p>
          {cancelling?.kind === "analysis"
            ? "Det som allerede er kontrollert, beholdes. For resten vises resultatene fra forrige kontroll."
            : "Jobben stopper så snart oppgaven den holder på med, er ferdig."}
        </p>
      </ConfirmDialog>
    </div>
  );
}

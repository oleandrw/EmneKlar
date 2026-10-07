import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, CircleQuestionMark, LoaderCircle, Play, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router";

import { Alert, Badge, Button, Dialog, Spinner, Switch, TextField, useToast } from "../../design-system";
import { api } from "../api/client";
import type { Job } from "../api/types";
import { courseLabel, useCourses, useCurrentCourse, useSelectCourse } from "../course";
import { useRefreshSession, useSession } from "../session";
import { useUi } from "../ui";

export function CourseSelector() {
  const session = useSession();
  const { course, courseId } = useCurrentCourse();
  const courses = useCourses(session.canvas.token_configured);
  const select = useSelectCourse();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const all = courses.data?.courses ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter((c) => `${c.name} ${c.course_code ?? ""} ${c.term_name ?? ""}`.toLowerCase().includes(q));
  }, [courses.data, query]);

  if (!session.canvas.token_configured) return null;
  const label = courseId && !course && courses.isPending ? "Laster emne …" : courseLabel(course);

  return (
    <>
      <button
        type="button"
        className="ek-course-button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        title={course ? course.name : undefined}
      >
        <span className="ek-visually-hidden">Valgt emne: </span>
        <span className="ek-course-button__label">{label}</span>
        <ChevronDown aria-hidden="true" />
      </button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Velg emne"
        description="Emnet gjelder for alle deler av EmneKlar til du bytter."
        initialFocusRef={searchRef}
        size="md"
      >
        <div className="ek-stack">
          <TextField
            ref={searchRef}
            label="Søk etter emne"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Emnekode, navn eller semester"
          />
          {courses.isPending ? <Spinner label="Henter emner fra Canvas …" /> : null}
          {courses.error ? (
            <Alert tone="danger" role="alert" title="Kunne ikke hente emner">
              {(courses.error as Error).message}
            </Alert>
          ) : null}
          {select.error ? (
            <Alert tone="danger" role="alert" title="Kunne ikke bytte emne">
              {(select.error as Error).message}
            </Alert>
          ) : null}
          <p className="ek-small ek-muted" aria-live="polite">
            {courses.data ? `${filtered.length} av ${courses.data.courses.length} emner` : null}
          </p>
          <ul className="ek-course-list" aria-label="Emner">
            {filtered.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  className="ek-course-option"
                  aria-current={c.id === courseId ? "true" : undefined}
                  onClick={() =>
                    select.mutate(c.id, {
                      onSuccess: () => {
                        setOpen(false);
                        setQuery("");
                      },
                    })
                  }
                >
                  <span className="ek-strong">{c.course_code ?? c.name}</span>
                  <span className="ek-xs ek-muted">
                    {c.name}
                    {c.term_name ? ` · ${c.term_name}` : ""}
                    {c.workflow_state === "unpublished" ? " · Ikke publisert" : ""}
                    {c.id === courseId ? " · Valgt" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {courses.data && filtered.length === 0 ? (
            <p className="ek-small ek-muted">
              <Search aria-hidden="true" size={14} /> Ingen emner passer søket.
            </p>
          ) : null}
        </div>
      </Dialog>
    </>
  );
}

export function DryRunToggle() {
  const session = useSession();
  const refresh = useRefreshSession();
  const toast = useToast();
  const mutation = useMutation({
    mutationFn: (enabled: boolean) => api.put<{ dry_run: boolean }>("/api/system/dry-run", { enabled }),
    onSuccess: async (data) => {
      await refresh();
      toast.show({
        tone: data.dry_run ? "info" : "success",
        title: data.dry_run ? "Dry run er slått på" : "Dry run er slått av",
        body: data.dry_run
          ? "Ingen endringer sendes til Canvas. Analyse, forhåndsvisning og endringskø fungerer som vanlig."
          : "Godkjente endringer kan nå sendes til Canvas.",
      });
    },
  });
  return (
    <Switch
      label="Dry run"
      checked={session.dry_run}
      disabled={mutation.isPending}
      onChange={(checked) => mutation.mutate(checked)}
    />
  );
}

export interface ChangeSummary {
  pending: number;
  by_domain: Record<string, number>;
}

export function useChangeSummary(courseId: string | null) {
  return useQuery({
    queryKey: ["changes", "summary", courseId],
    queryFn: () => api.get<ChangeSummary>(`/api/changes/summary${courseId ? `?course_id=${courseId}` : ""}`),
    refetchInterval: 15_000,
  });
}

/** Pending changes: a green pill when something is ready to review, calm otherwise. */
export function ChangeSetButton() {
  const { courseId } = useCurrentCourse();
  const summary = useChangeSummary(courseId);
  const ui = useUi();
  const count = summary.data?.pending ?? 0;
  return (
    <button type="button" className="ek-changes-pill" data-tone={count > 0 ? "success" : "neutral"} onClick={ui.openChanges}>
      <span className="ek-changes-pill__dot" aria-hidden="true" />
      {count === 1 ? "1 endring klar" : `${count} endringer klare`}
      <ChevronRight aria-hidden="true" />
    </button>
  );
}

export function HelpButton() {
  return (
    <Link to="/hjelp" className="ek-btn ek-btn--ghost ek-btn--icon" aria-label="Hjelp" title="Hjelp">
      <CircleQuestionMark aria-hidden="true" />
    </Link>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1][0] ?? "") : "";
  return (first + last).toUpperCase();
}

/** The Canvas user EmneKlar is connected as; opens the Canvas connection settings. */
export function UserChip() {
  const session = useSession();
  const identity = session.canvas.identity;
  if (!identity) return null;
  let host = "Canvas";
  try {
    if (session.canvas.base_url) host = new URL(session.canvas.base_url).host;
  } catch {
    // keep the generic label
  }
  return (
    <Link to="/innstillinger/canvas-tilkobling" className="ek-user" title={`Innlogget i Canvas som ${identity.name}`}>
      <span className="ek-user__avatar" aria-hidden="true">
        {initials(identity.name)}
      </span>
      <span className="ek-user__text">
        <span className="ek-user__name">{identity.name}</span>
        <span className="ek-user__sub">
          <span className="ek-visually-hidden">Canvas-tilkobling: </span>
          {host}
        </span>
      </span>
    </Link>
  );
}

export function RunAnalysisButton() {
  const ui = useUi();
  const { courseId } = useCurrentCourse();
  return (
    <Button
      variant="primary"
      size="lg"
      icon={<Play aria-hidden="true" />}
      onClick={() => ui.openAnalysis()}
      disabled={!courseId}
      title={courseId ? undefined : "Velg et emne først"}
    >
      Kjør ny analyse
    </Button>
  );
}

export function useActiveJobs() {
  return useQuery({
    queryKey: ["jobs", "active"],
    queryFn: () => api.get<{ jobs: Job[] }>("/api/jobs?active=true"),
    refetchInterval: (query) => ((query.state.data?.jobs.length ?? 0) > 0 ? 2_000 : 10_000),
  });
}

export function JobIndicator() {
  const jobs = useActiveJobs();
  const ui = useUi();
  const client = useQueryClient();
  const active = jobs.data?.jobs ?? [];
  if (active.length === 0) return null;
  const job = active[0];
  const percent = job.progress.percent;
  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={() => {
        ui.watchJob(job.id);
        ui.openAnalysis();
        void client.invalidateQueries({ queryKey: ["jobs", job.id] });
      }}
      icon={<LoaderCircle aria-hidden="true" className="ek-spinner-icon" />}
    >
      <span>
        {job.title}
        {percent !== null ? ` – ${percent} %` : " – starter"}
        {job.status === "paused" ? " (pause)" : ""}
      </span>
      {active.length > 1 ? <Badge>{`+${active.length - 1}`}</Badge> : null}
    </Button>
  );
}

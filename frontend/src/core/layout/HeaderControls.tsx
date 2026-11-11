import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Search, Star } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";

import { Alert, Button, Dialog, Spinner, TextField } from "../../design-system";
import { HeaderAnalysisButton } from "../../features/analysis/AnalysisStatus";
import { api } from "../api/client";
import type { Course } from "../api/types";
import {
  courseLabel,
  courseQuery,
  matchCourses,
  useCourses,
  useCurrentCourse,
  useFavoriteCourse,
  useSelectCourse,
  type CourseList,
} from "../course";
import { useSession } from "../session";
import { useUi } from "../ui";

/** One course in the selector: choose it, or mark it as a favourite (a toggle button beside it). */
function CourseRow({ course: c, current, onSelect }: { course: Course; current: boolean; onSelect: () => void }) {
  const favorite = useFavoriteCourse();
  const name = c.course_code ?? c.name;
  return (
    <li className="ek-course-row">
      <button type="button" className="ek-course-option" aria-current={current ? "true" : undefined} onClick={onSelect}>
        <span className="ek-strong">{name}</span>
        <span className="ek-xs ek-muted">
          {c.name}
          {` · ID ${c.id}`}
          {c.term_name ? ` · ${c.term_name}` : ""}
          {c.workflow_state === "unpublished" ? " · Ikke publisert" : ""}
          {current ? " · Valgt" : ""}
        </span>
      </button>
      <button type="button" className="ek-course-star" aria-pressed={Boolean(c.favorite)} aria-label={`Favoritt: ${name}`}
        title={c.favorite ? "Fjern fra favoritter" : "Legg til i favoritter"}
        onClick={() => favorite.mutate({ courseId: c.id, favorite: !c.favorite })}>
        <Star aria-hidden="true" fill={c.favorite ? "currentColor" : "none"} />
      </button>
    </li>
  );
}

export function CourseSelector() {
  const session = useSession();
  const { course, courseId } = useCurrentCourse();
  const courses = useCourses(session.canvas.token_configured);
  const select = useSelectCourse();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const reload = useMutation({
    mutationFn: () => api.get<CourseList>("/api/courses?refresh=true"),
    onSuccess: (data) => client.setQueryData(["courses"], data),
  });

  // «Åpne EmneKlar» after the setup without a start course opens the course selector (…?velg-emne=1).
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    if (params.get("velg-emne") !== "1") return;
    setOpen(true);
    const rest = new URLSearchParams(params);
    rest.delete("velg-emne");
    setParams(rest, { replace: true });
  }, [params, setParams]);

  const filtered = useMemo(() => matchCourses(courses.data?.courses ?? [], query), [courses.data, query]);
  const favorites = filtered.filter((c) => c.favorite);
  const others = filtered.filter((c) => !c.favorite);
  const searchedId = /^\d+$/.test(courseQuery(query)) ? courseQuery(query) : null;

  if (!session.canvas.token_configured) return null;
  const label = courseId && !course && courses.isPending ? "Laster emne …" : courseLabel(course);
  const choose = (id: string) =>
    select.mutate(id, {
      onSuccess: () => {
        setOpen(false);
        setQuery("");
      },
    });

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
            placeholder="Emnekode, navn, semester eller emne-ID"
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
          {favorites.length ? (
            <section className="ek-stack" data-gap="2" aria-labelledby="emner-favoritter">
              <h3 id="emner-favoritter" className="ek-course-group">Favoritter</h3>
              <ul className="ek-course-list" aria-labelledby="emner-favoritter">
                {favorites.map((c) => <CourseRow key={c.id} course={c} current={c.id === courseId} onSelect={() => choose(c.id)} />)}
              </ul>
            </section>
          ) : null}
          {others.length ? (
            <section className="ek-stack" data-gap="2" aria-labelledby="emner-alle">
              <h3 id="emner-alle" className="ek-course-group">{favorites.length ? "Andre emner" : "Emner"}</h3>
              <ul className="ek-course-list" aria-labelledby="emner-alle">
                {others.map((c) => <CourseRow key={c.id} course={c} current={c.id === courseId} onSelect={() => choose(c.id)} />)}
              </ul>
            </section>
          ) : null}
          {courses.data && filtered.length === 0 ? (
            <div className="ek-stack" data-gap="2">
              <p className="ek-small ek-muted">
                <Search aria-hidden="true" size={14} />{" "}
                {searchedId ? `Fant ikke emne-ID ${searchedId} blant emnene dine.` : "Ingen emner passer søket."} Listen viser
                emner der du er lærer, assistent eller designer, og som ikke er avsluttet.
              </p>
              <div>
                <Button size="sm" loading={reload.isPending} onClick={() => reload.mutate()}>Hent emnelisten på nytt fra Canvas</Button>
              </div>
              {reload.error ? <Alert tone="danger" role="alert">{(reload.error as Error).message}</Alert> : null}
            </div>
          ) : null}
          <p className="ek-xs ek-subtle">Favorittene lagres i EmneKlar og endrer ikke favorittene dine i Canvas.</p>
        </div>
      </Dialog>
    </>
  );
}

export interface ChangeSummary {
  pending: number;
  approved: number;
  problems: number;
  courses: number;
  by_domain: Record<string, number>;
}

/** The whole change queue (all courses): one queue, one «Publiser til Canvas». */
export function useChangeSummary() {
  return useQuery({
    queryKey: ["changes", "summary"],
    queryFn: () => api.get<ChangeSummary>("/api/changes/summary"),
    refetchInterval: 15_000,
  });
}

/** The change queue: green when approved changes are ready to publish, amber when something needs attention. */
export function ChangeSetButton() {
  const summary = useChangeSummary();
  const ui = useUi();
  const pending = summary.data?.pending ?? 0;
  const approved = summary.data?.approved ?? 0;
  const problems = summary.data?.problems ?? 0;
  const tone = problems > 0 ? "warning" : pending > 0 ? "success" : "neutral";
  const label = approved > 0
    ? `${approved} godkjent${approved === 1 ? "" : "e"} – klar til publisering`
    : pending === 1 ? "1 endring i kø" : `${pending} endringer i kø`;
  return (
    <button type="button" className="ek-changes-pill" data-tone={tone} onClick={ui.openChanges}>
      <span className="ek-changes-pill__dot" aria-hidden="true" />
      {label}
      {problems > 0 ? <span className="ek-visually-hidden">, {problems} må ses på</span> : null}
      <ChevronRight aria-hidden="true" />
    </button>
  );
}

/** The one analysis button: its text and action follow the page (see HeaderAnalysisButton). */
export function RunAnalysisButton() {
  return <HeaderAnalysisButton />;
}

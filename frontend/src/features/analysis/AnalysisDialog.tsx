import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import type { Job } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { useCourseAnalysis, useJobs } from "../../core/jobs";
import { DOMAIN_LABEL, type AnalysisDomain } from "../../core/labels";
import { useSession } from "../../core/session";
import { useUi } from "../../core/ui";
import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  Fieldset,
  RadioGroup,
  Spinner,
  TextField,
} from "../../design-system";
import { ProgressPanel } from "./ProgressPanel";
import { FINAL_STATUSES, useJob } from "./useJob";

type Scope = "course" | "modules" | "items";

interface ContentIndex {
  modules: { id: string; name: string; items_count: number }[];
  items: { object_type: string; object_id: string; title: string; module: string | null }[];
  partial: boolean;
}

const DOMAIN_HINTS: Record<AnalysisDomain, string> = {
  accessibility: "Bilder, overskrifter, lenker, tabeller, kontrast, video og dokumenter.",
  content_quality: "Døde lenker, medier som ikke virker og unødvendig kode.",
  structure: "Moduler, rekkefølge, navngiving og studentreisen.",
  quiz: "Klassiske quizer: fasit, svaralternativer og duplikater.",
};
const RESULT_PATHS: Record<AnalysisDomain, string> = {
  accessibility: "/universell-utforming",
  content_quality: "/innholdskvalitet",
  structure: "/emnestruktur",
  quiz: "/quizassistent",
};
const TYPE_LABEL: Record<string, string> = { page: "Side", assignment: "Oppgave", discussion: "Diskusjon", quiz: "Quiz" };

export function AnalysisDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ui = useUi();
  const session = useSession();
  const { courseId, course } = useCurrentCourse();
  const jobs = useJobs();
  // The details of an analysis («Detaljer» in «Analysestatus»), or the one running for the course: never a second one.
  const { running } = useCourseAnalysis();
  const jobId = ui.watchedJobId ?? running?.id ?? null;
  const job = useJob(jobId);

  const [scope, setScope] = useState<Scope>("course");
  const [domains, setDomains] = useState<AnalysisDomain[]>(session.analysis.default_domains);
  const [modules, setModules] = useState<string[]>([]);
  const [items, setItems] = useState<string[]>([]);
  const [filter, setFilter] = useState("");

  // From a page for one area (the header button follows the page) only that area is analysed – never a full analysis.
  const area = ui.analysisPreset?.area ?? null;
  useEffect(() => {
    if (open) setDomains(area ? [area] : (ui.analysisPreset?.domains ?? session.analysis.default_domains));
  }, [open, area, ui.analysisPreset, session.analysis.default_domains]);

  const index = useQuery({
    queryKey: ["content-index", courseId],
    queryFn: () => api.get<ContentIndex>(`/api/courses/${courseId}/content-index`),
    enabled: open && Boolean(courseId) && scope !== "course",
    staleTime: 60_000,
  });

  const start = useMutation({
    mutationFn: (body: object) => api.post<Job>("/api/analysis", body),
    // The analysis runs in the background: the dialog closes and «Analysestatus» opens as the confirmation.
    onSuccess: (created) => {
      jobs.track(created);
      ui.watchJob(null);
      onClose();
    },
  });

  const filteredItems = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (index.data?.items ?? []).filter((i) => !q || `${i.title} ${i.module ?? ""}`.toLowerCase().includes(q));
  }, [index.data, filter]);

  const quizEnabled = session.flags.quiz_assistant !== false;
  const availableDomains: AnalysisDomain[] = [
    "accessibility", "content_quality", "structure", ...(quizEnabled ? (["quiz"] as AnalysisDomain[]) : []),
  ];
  const canStart =
    Boolean(courseId) &&
    domains.length > 0 &&
    (scope === "course" || (scope === "modules" ? modules.length > 0 : items.length > 0));

  const submit = (full: boolean) => {
    if (!courseId) return;
    start.mutate(
      full
        ? { course_id: courseId, scope: "course", domains: availableDomains }
        : {
            course_id: courseId,
            scope,
            domains,
            module_ids: scope === "modules" ? modules : [],
            items:
              scope === "items"
                ? items.map((key) => {
                    const [object_type, ...rest] = key.split(":");
                    return { object_type, object_id: rest.join(":") };
                  })
                : [],
          },
    );
  };

  const close = () => {
    onClose();
    if (job.data && FINAL_STATUSES.has(job.data.status)) ui.watchJob(null);
  };

  const showProgress = Boolean(jobId && job.data);
  const done = job.data && FINAL_STATUSES.has(job.data.status);
  const ranDomains = ((job.data?.params?.domains ?? []) as AnalysisDomain[]).filter((d) => d in RESULT_PATHS);

  return (
    <Dialog
      open={open}
      onClose={close}
      size="lg"
      title={showProgress ? (job.data?.title ?? "Analyse")
        : area ? `Analyser ${DOMAIN_LABEL[area].toLowerCase()}` : "Analyser hele emnet"}
      description={course ? `${course.course_code ?? ""} ${course.name}`.trim() : undefined}
      footer={
        showProgress ? (
          <Button variant="primary" onClick={close}>
            Lukk
          </Button>
        ) : (
          <>
            <Button onClick={close}>Avbryt</Button>
            {area ? null : (
              <Button onClick={() => submit(true)} disabled={!courseId || start.isPending}>
                Full analyse
              </Button>
            )}
            <Button variant="primary" onClick={() => submit(false)} disabled={!canStart} loading={start.isPending}>
              Start analyse
            </Button>
          </>
        )
      }
    >
      {showProgress && job.data ? (
        <div className="ek-stack" data-gap="6">
          <ProgressPanel job={job.data} onBackground={close} />
          {done && job.data.status !== "failed" ? (
            <div className="ek-stack" data-gap="2">
              <h3>Se resultatene</h3>
              <ul className="ek-cluster ek-list-reset">
                {ranDomains.map((d) => (
                    <li key={d}>
                      <Link to={RESULT_PATHS[d]} onClick={close}>
                        {DOMAIN_LABEL[d]}
                      </Link>
                    </li>
                  ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="ek-stack" data-gap="6">
          {start.error ? (
            <Alert tone="danger" role="alert" title="Kunne ikke starte analysen">
              {(start.error as Error).message}
            </Alert>
          ) : null}
          <RadioGroup<Scope>
            legend="Omfang"
            name="scope"
            value={scope}
            onChange={setScope}
            options={[
              { value: "course", label: "Hele emnet" },
              { value: "modules", label: "Valgte moduler" },
              { value: "items", label: "Enkeltelementer" },
            ]}
          />
          {scope !== "course" ? (
            index.isPending ? (
              <Spinner label="Henter moduler og innhold …" />
            ) : index.error ? (
              <Alert tone="danger" title="Kunne ikke hente innholdet">
                {(index.error as Error).message}
              </Alert>
            ) : scope === "modules" ? (
              <Fieldset legend="Moduler" hint={`${modules.length} valgt`}>
                {(index.data?.modules ?? []).map((m) => (
                  <Checkbox
                    key={m.id}
                    label={`${m.name} (${m.items_count} elementer)`}
                    checked={modules.includes(m.id)}
                    onChange={(e) =>
                      setModules((cur) => (e.target.checked ? [...cur, m.id] : cur.filter((x) => x !== m.id)))
                    }
                  />
                ))}
              </Fieldset>
            ) : (
              <div className="ek-stack" data-gap="2">
                <TextField label="Filtrer innhold" type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
                <Fieldset legend="Elementer" hint={`${items.length} valgt`}>
                  <div className="ek-stack ek-scroll-box" data-gap="1">
                    {filteredItems.map((i) => {
                      const key = `${i.object_type}:${i.object_id}`;
                      return (
                        <Checkbox
                          key={key}
                          label={`${TYPE_LABEL[i.object_type] ?? i.object_type}: ${i.title}`}
                          hint={i.module ?? "Ikke i noen modul"}
                          checked={items.includes(key)}
                          onChange={(e) =>
                            setItems((cur) => (e.target.checked ? [...cur, key] : cur.filter((x) => x !== key)))
                          }
                        />
                      );
                    })}
                  </div>
                </Fieldset>
              </div>
            )
          ) : null}
          {area ? (
            <p className="ek-small">
              <span className="ek-strong">Område: {DOMAIN_LABEL[area]}.</span> {DOMAIN_HINTS[area]} Analysen leser bare
              fra Canvas – ingenting endres.
            </p>
          ) : (
            <>
              <Fieldset legend="Analyseområder" hint="Velg hva som skal kontrolleres.">
                {availableDomains.map((d) => (
                  <Checkbox
                    key={d}
                    label={DOMAIN_LABEL[d]}
                    hint={DOMAIN_HINTS[d]}
                    checked={domains.includes(d)}
                    onChange={(e) => setDomains((cur) => (e.target.checked ? [...cur, d] : cur.filter((x) => x !== d)))}
                  />
                ))}
              </Fieldset>
              <p className="ek-small ek-muted">
                «Full analyse» kontrollerer hele emnet innen alle områder. Analysen leser bare fra Canvas – ingenting
                endres.
              </p>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

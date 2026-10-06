import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import type { Job } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { DOMAIN_LABEL, type Domain } from "../../core/labels";
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
  useToast,
} from "../../design-system";
import { useActiveJobs } from "../../core/layout/HeaderControls";
import { ProgressPanel } from "./ProgressPanel";
import { FINAL_STATUSES, useJob } from "./useJob";

type Scope = "course" | "modules" | "items";

interface ContentIndex {
  modules: { id: string; name: string; items_count: number }[];
  items: { object_type: string; object_id: string; title: string; module: string | null }[];
  partial: boolean;
}

const DOMAIN_HINTS: Record<Domain, string> = {
  accessibility: "Bilder, overskrifter, lenker, tabeller, kontrast, video og dokumenter.",
  content_quality: "Døde lenker, medier som ikke virker og unødvendig kode.",
  structure: "Moduler, rekkefølge, navngiving og studentreisen.",
  quiz: "Klassiske quizer: fasit, svaralternativer og duplikater.",
};
const RESULT_PATHS: Record<Domain, string> = {
  accessibility: "/universell-utforming",
  content_quality: "/innholdskvalitet",
  structure: "/emnestruktur",
  quiz: "/quizassistent",
};
const TYPE_LABEL: Record<string, string> = { page: "Side", assignment: "Oppgave", discussion: "Diskusjon", quiz: "Quiz" };

function useNotifyOnCompletion(job: Job | undefined) {
  const toast = useToast();
  const session = useSession();
  const client = useQueryClient();
  const [notified, setNotified] = useState<string | null>(null);
  useEffect(() => {
    if (!job || !FINAL_STATUSES.has(job.status) || notified === job.id) return;
    setNotified(job.id);
    void client.invalidateQueries({ queryKey: ["findings"] });
    void client.invalidateQueries({ queryKey: ["overview"] });
    void client.invalidateQueries({ queryKey: ["runs"] });
    if (!session.notifications.notify_job_complete) return;
    const ok = job.status === "completed";
    toast.show({
      tone: ok ? "success" : job.status === "failed" ? "danger" : "warning",
      title: ok ? "Analysen er ferdig" : `Analysen ble ${job.status === "failed" ? "ikke fullført" : "avbrutt"}`,
      body: ok ? "Resultatene er oppdatert." : (job.error ?? undefined),
    });
    if (session.notifications.browser_notifications && "Notification" in window && Notification.permission === "granted") {
      new Notification("EmneKlar", { body: ok ? "Analysen er ferdig." : "Analysen ble ikke fullført." });
    }
  }, [job, notified, toast, session, client]);
}

export function AnalysisDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ui = useUi();
  const session = useSession();
  const { courseId, course } = useCurrentCourse();
  const active = useActiveJobs();
  const runningAnalysis = active.data?.jobs.find((j) => j.kind === "analysis" && j.course_id === courseId);
  const jobId = ui.watchedJobId ?? runningAnalysis?.id ?? null;
  const job = useJob(jobId);
  useNotifyOnCompletion(job.data);

  const [scope, setScope] = useState<Scope>("course");
  const [domains, setDomains] = useState<Domain[]>(["accessibility", "content_quality", "structure"]);
  const [modules, setModules] = useState<string[]>([]);
  const [items, setItems] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const client = useQueryClient();

  useEffect(() => {
    if (open && ui.analysisPreset?.domains) setDomains(ui.analysisPreset.domains);
  }, [open, ui.analysisPreset]);

  const index = useQuery({
    queryKey: ["content-index", courseId],
    queryFn: () => api.get<ContentIndex>(`/api/courses/${courseId}/content-index`),
    enabled: open && Boolean(courseId) && scope !== "course",
    staleTime: 60_000,
  });

  const start = useMutation({
    mutationFn: (body: object) => api.post<Job>("/api/analysis", body),
    onSuccess: (created) => {
      ui.watchJob(created.id);
      client.setQueryData(["jobs", created.id], created);
      void client.invalidateQueries({ queryKey: ["jobs", "active"] });
    },
  });

  const filteredItems = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (index.data?.items ?? []).filter((i) => !q || `${i.title} ${i.module ?? ""}`.toLowerCase().includes(q));
  }, [index.data, filter]);

  const quizEnabled = session.flags.quiz_assistant !== false;
  const availableDomains: Domain[] = ["accessibility", "content_quality", "structure", ...(quizEnabled ? (["quiz"] as Domain[]) : [])];
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
  const ranDomains = ((job.data?.params?.domains ?? []) as Domain[]).filter((d) => d in RESULT_PATHS);

  return (
    <Dialog
      open={open}
      onClose={close}
      size="lg"
      title={showProgress ? (job.data?.title ?? "Analyse") : "Kjør ny analyse"}
      description={course ? `${course.course_code ?? ""} ${course.name}`.trim() : undefined}
      footer={
        showProgress ? (
          <>
            {done ? (
              <Button
                onClick={() => {
                  ui.watchJob(null);
                }}
              >
                Ny analyse
              </Button>
            ) : null}
            <Button variant="primary" onClick={close}>
              Lukk
            </Button>
          </>
        ) : (
          <>
            <Button onClick={close}>Avbryt</Button>
            <Button onClick={() => submit(true)} disabled={!courseId || start.isPending}>
              Full analyse
            </Button>
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
                  <div style={{ maxHeight: "16rem", overflowY: "auto" }} className="ek-stack" data-gap="1">
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
            «Full analyse» kontrollerer hele emnet innen alle områder. Analysen leser bare fra Canvas – ingenting endres.
          </p>
        </div>
      )}
    </Dialog>
  );
}

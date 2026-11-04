// Canvas-verktøy → KI-bildeassistent: context-aware, consistent illustrations for a course, a module or a page.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useCurrentCourse } from "../../../core/course";
import { formatDateTime } from "../../../core/format";
import { HelpLink } from "../../../core/HelpLink";
import { useSession } from "../../../core/session";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Spinner,
  Stepper,
} from "../../../design-system";
import { AnalyseStep } from "./AnalyseStep";
import { DEFAULT_SCOPE, RUN_TONE, useCatalog, useIllustrationStatus, useScopeIndex, type IllustrationSettings, type RunSummary, type Scope } from "./api";
import { DesignStep } from "./DesignStep";
import { ModelStep } from "./ModelStep";
import { PublishStep } from "./PublishStep";
import { ReviewStep } from "./ReviewStep";
import { scopeReady, ScopeStep } from "./ScopeStep";

type StepId = "omfang" | "modeller" | "design" | "analyse" | "generer" | "gjennomga" | "publiser";

const SCOPE_LABEL: Record<string, string> = { course: "Hele emnet", module: "Én modul", modules: "Flere moduler", page: "Én side" };

function RunList({ runs, onOpen }: { runs: RunSummary[]; onOpen: (run: RunSummary) => void }) {
  if (!runs.length) return null;
  return (
    <Card title="Tidligere kjøringer" description="Åpne en kjøring for å gjennomgå, fortsette eller publisere. Ny kjøring finner nye sider og manglende illustrasjoner uten å lage dubletter."
      headingLevel={2}>
      <ul className="ek-stack" data-gap="2">
        {runs.slice(0, 5).map((run) => (
          <li key={run.id} className="ek-cluster" data-justify="between">
            <span className="ek-cluster" data-gap="2">
              <strong>{SCOPE_LABEL[run.scope.type] ?? run.scope.type}</strong>
              <Badge tone={RUN_TONE[run.status] ?? "neutral"}>{run.status_label}</Badge>
              {run.created_at ? <span className="ek-small ek-muted">{formatDateTime(run.created_at)}</span> : null}
              {run.stats.inventory ? <span className="ek-small ek-muted">{run.stats.inventory.pages_in_scope} sider</span> : null}
            </span>
            <Button size="sm" onClick={() => onOpen(run)}>Åpne</Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function IllustrationAssistant() {
  const { courseId } = useCurrentCourse();
  const session = useSession();
  const client = useQueryClient();
  const status = useIllustrationStatus(courseId);
  const catalog = useCatalog();
  const index = useScopeIndex(courseId);
  const [step, setStep] = useState<StepId>("omfang");
  const [scope, setScope] = useState<Scope>(DEFAULT_SCOPE);
  const [settings, setSettings] = useState<IllustrationSettings | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  useEffect(() => {
    if (status.data && settings === null) setSettings(status.data.settings);
  }, [status.data, settings]);
  useEffect(() => {
    setRunId(null);
    setStep("omfang");
    setScope(DEFAULT_SCOPE);
  }, [courseId]);

  const header = (
    <PageHeader title="KI-bildeassistent"
      description="Analyserer undervisningsinnholdet, foreslår faglig presise illustrasjoner i én gjennomgående stil, og setter dem inn med alternativ tekst og bildetekst etter godkjenning."
      actions={<HelpLink topic="canvas-verktoy" />}
      status={<Badge tone="violet">KI-forslag – må vurderes</Badge>} />
  );
  if (session.flags.illustration_assistant === false) {
    return <>{header}<Alert tone="info">KI-bildeassistenten er slått av under Innstillinger → Avanserte innstillinger.</Alert></>;
  }
  if (!courseId) return <>{header}<EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState></>;
  if (status.isPending || catalog.isPending || !settings) return <>{header}<Spinner label="Henter KI-bildeassistenten …" /></>;
  if (status.error || catalog.error || !status.data || !catalog.data) {
    return <>{header}<Alert tone="danger">Kunne ikke hente KI-bildeassistenten. {(status.error ?? catalog.error)?.message}</Alert></>;
  }
  const data = status.data;
  const ready = scopeReady(scope);
  const steps = [
    { id: "omfang" as const, label: "Velg omfang", done: ready && step !== "omfang" },
    { id: "modeller" as const, label: "Velg KI-modeller" },
    { id: "design" as const, label: "Velg designprofil", done: Boolean(data.design) },
    { id: "analyse" as const, label: "Analyser innhold", disabled: !ready && runId === null, done: runId !== null },
    { id: "generer" as const, label: "Generer", disabled: runId === null },
    { id: "gjennomga" as const, label: "Gjennomgå", disabled: runId === null },
    { id: "publiser" as const, label: "Publiser", disabled: runId === null },
  ];
  const next: Record<StepId, StepId | null> = { omfang: "modeller", modeller: "design", design: "analyse", analyse: null,
    generer: "gjennomga", gjennomga: "publiser", publiser: null };
  const nextStep = next[step];

  return (
    <>
      {header}
      <div className="ek-stack" data-gap="6">
        {data.dry_run ? <Alert tone="info" title="Dry run er på">Du kan analysere og lage bilder, men ingenting sendes til Canvas.</Alert> : null}
        {step === "omfang" ? <RunList runs={data.runs} onOpen={(run) => {
          setRunId(run.id);
          setStep(run.status === "review" || run.status === "completed" ? "gjennomga" : "generer");
        }} /> : null}
        <div className="ek-wizard">
          <Stepper label="Steg i KI-bildeassistenten" steps={steps} current={step} onSelect={setStep} />
          <div className="ek-stack" data-gap="4">
            {step === "omfang" ? (
              <ScopeStep scope={scope} onChange={setScope} index={index.data} loading={index.isPending} error={index.error?.message ?? null} />
            ) : null}
            {step === "modeller" ? <ModelStep settings={settings} onChange={setSettings} status={data} catalog={catalog.data} /> : null}
            {step === "design" ? <DesignStep courseId={courseId} status={data} catalog={catalog.data} /> : null}
            {step === "analyse" ? (
              <AnalyseStep courseId={courseId} scope={scope} settings={settings} catalog={catalog.data} busyJobId={data.busy_job?.id ?? null}
                onStarted={(run) => setRunId(run.id)}
                onDone={(job) => {
                  void client.invalidateQueries({ queryKey: ["illustrations"] });
                  setStep(job.result?.status === "review" ? "gjennomga" : "generer");
                }} />
            ) : null}
            {step === "generer" && runId !== null ? (
              <ReviewStep runId={runId} catalog={catalog.data} stage="generate" onPublish={() => setStep("publiser")} />
            ) : null}
            {step === "gjennomga" && runId !== null ? <ReviewStep runId={runId} catalog={catalog.data} onPublish={() => setStep("publiser")} /> : null}
            {step === "publiser" && runId !== null ? <PublishStep runId={runId} catalog={catalog.data} /> : null}
            {nextStep ? (
              <div className="ek-cluster" data-justify="end">
                <Button variant="primary" onClick={() => setStep(nextStep)} disabled={step === "omfang" && !ready}>Neste</Button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </>
  );
}

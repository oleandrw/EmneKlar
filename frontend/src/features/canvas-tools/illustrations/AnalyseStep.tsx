// Step 3 – Analyser: map the course in Canvas (no AI), confirm what is sent, run the analysis, and show the plan:
// how many modules and pages were analysed, which pages get images, where, and why.
import { useMutation } from "@tanstack/react-query";
import { Calculator, FileText, Images, Layers, Play, Wand2 } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "../../../core/api/client";
import type { Job } from "../../../core/api/types";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  DataTable,
  Disclosure,
  KeyFigure,
  KeyFigureList,
  SelectField,
  Spinner,
  type Column,
} from "../../../design-system";
import { JobRunner } from "../../analysis/JobRunner";
import { money, useRun, type Catalog, type Estimate, type EstimateLine, type IllustrationSettings, type RunSummary, type Scope } from "./api";

export const JOB_WORDING = {
  noun: "jobben",
  current: "Nå behandles",
  findingsTitle: "Underveis",
  findingsEmpty: "Ingen resultater ennå.",
  cancelNote: "Det som allerede er analysert og laget, beholdes. Du kan fortsette senere.",
};

/** The plan after the analysis: counts and, per module and page, where images are proposed and why. */
export function PlanSummary({ runId, onNext }: { runId: number; onNext: () => void }) {
  const run = useRun(runId);
  if (run.isPending) return <Spinner label="Henter bildeplanen …" />;
  if (!run.data) return null;
  const { overview, illustrations } = run.data;
  const pages = overview.flatMap((m) => m.pages);
  const withImages = pages.filter((p) => p.proposed > 0);
  return (
    <div className="ek-stack" data-gap="5">
      <KeyFigureList label="Resultat av analysen">
        <KeyFigure icon={<Layers />} tone="info" value={overview.filter((m) => m.module_id !== "__outside__").length} label="Moduler analysert" />
        <KeyFigure icon={<FileText />} tone="info" value={pages.length} label="Sider analysert" />
        <KeyFigure icon={<Images />} tone="violet" value={illustrations.filter((i) => i.status !== "skipped").length} label="Foreslåtte bilder" />
        <KeyFigure icon={<FileText />} value={withImages.length} label="Sider som får bilder" />
      </KeyFigureList>
      {overview.map((module) => (
        <div key={module.module_id} className="ek-stack" data-gap="2">
          <h3>{module.name}</h3>
          <ul className="ek-stack" data-gap="2">
            {module.pages.map((page) => (
              <li key={page.page_url}>
                <strong>{page.title}</strong>
                <span className="ek-small ek-muted"> – {page.proposed === 0 ? "Ingen illustrasjon anbefalt" : `${page.proposed} foreslått${page.proposed === 1 ? "" : "e"} bilde${page.proposed === 1 ? "" : "r"}`}</span>
                {page.illustrations.length ? (
                  <ul className="ek-stack" data-gap="1">
                    {page.illustrations.map((i) => (
                      <li key={i.id} className="ek-small">
                        <span className="ek-strong">{i.plan.pedagogical_purpose ?? i.plan.concept}</span>
                        <br />{i.placement_label}{i.plan.placement_reason ? <span className="ek-muted"> – {i.plan.placement_reason}</span> : null}
                      </li>
                    ))}
                  </ul>
                ) : page.reason ? <p className="ek-small ek-muted">{page.reason}</p> : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <div>
        <Button variant="primary" icon={<Play aria-hidden="true" />} onClick={onNext}>Gå til «Generer og gjennomgå»</Button>
      </div>
    </div>
  );
}

export function AnalyseStep({ courseId, scope, settings, catalog, busyJobId, runId, onStarted, onDone, onNext }: {
  courseId: string;
  scope: Scope;
  settings: IllustrationSettings;
  catalog: Catalog;
  busyJobId: string | null;
  runId: number | null;
  onStarted: (run: RunSummary, job: Job) => void;
  onDone: (job: Job) => void;
  onNext: () => void;
}) {
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [consent, setConsent] = useState(false);
  const [generateNow, setGenerateNow] = useState(false);
  const [autoInsert, setAutoInsert] = useState(false);
  const [rights, setRights] = useState("");
  const [jobId, setJobId] = useState<string | null>(busyJobId);
  const [done, setDone] = useState(false);
  const body = { scope, settings };
  const calc = useMutation({
    mutationFn: () => api.post<Estimate>(`/api/courses/${courseId}/illustrations/estimate`, { ...body, mode: "full" }),
    onSuccess: (e) => {
      setEstimate(e);
      setConsent(false);
    },
  });
  const start = useMutation({
    mutationFn: () => api.post<{ run: RunSummary; job: Job }>(`/api/courses/${courseId}/illustrations/runs`, {
      ...body, mode: generateNow ? "full" : "plan", auto_insert: generateNow && autoInsert, confirmed: true,
      usage_rights: rights ? { use_justification: rights } : null,
    }),
    onSuccess: (r) => {
      setJobId(r.job.id);
      setDone(false);
      onStarted(r.run, r.job);
    },
  });

  const columns: Column<EstimateLine>[] = [
    { key: "label", header: "Del", rowHeader: true, cell: (l) => l.label },
    { key: "calls", header: "Antall kall", numeric: true, cell: (l) => (l.calls_low === l.calls_high ? l.calls_low : `${l.calls_low}–${l.calls_high}`) },
    { key: "cost", header: "Anslått kostnad", numeric: true, cell: (l) => (l.cost_low === null ? "ukjent pris"
      : `${money(l.cost_low, estimate?.estimate.currency)} – ${money(l.cost_high, estimate?.estimate.currency)}`) },
  ];
  const mustConsent = Boolean(estimate?.needs_confirmation);
  const rightsMissing = Boolean(estimate?.usage_rights_required && autoInsert && generateNow && !rights);
  const canStart = Boolean(estimate?.available) && (!mustConsent || consent) && !rightsMissing && !start.isPending;

  if (jobId && !done) {
    return (
      <Card title="3. Analyser" description="KI analyserer emnet, modulene og sidene og foreslår bilder og plassering. Jobben kjører i bakgrunnen.">
        <JobRunner jobId={jobId} wording={JOB_WORDING} onDone={(job) => {
          setDone(true);
          onDone(job);
        }} />
      </Card>
    );
  }
  if (done && runId !== null) {
    return (
      <Card title="3. Analyser" description="Bildeplanen er klar. Se gjennom forslagene, og gå videre for å lage bildene.">
        <PlanSummary runId={runId} onNext={onNext} />
      </Card>
    );
  }
  return (
    <Card title="3. Analyser" description="KI analyserer innholdet på emne-, modul- og sidenivå og foreslår bilder der de gir faglig verdi – med naturlig plassering i teksten.">
      <div className="ek-stack" data-gap="5">
        <div>
          <Button icon={<Calculator aria-hidden="true" />} onClick={() => calc.mutate()} loading={calc.isPending}>
            {estimate ? "Kartlegg på nytt" : "Kartlegg innholdet"}
          </Button>
        </div>
        {calc.error ? <Alert tone="danger" title="Kunne ikke kartlegge emnet">{calc.error.message}</Alert> : null}
        {estimate ? (
          <div className="ek-stack" data-gap="5">
            <p>
              {estimate.stats.pages_in_scope} side{estimate.stats.pages_in_scope === 1 ? "" : "r"} i {estimate.stats.modules_in_scope} modul{estimate.stats.modules_in_scope === 1 ? "" : "er"} analyseres.
              {estimate.stats.pages_in_several_modules ? ` ${estimate.stats.pages_in_several_modules} side(r) ligger i flere moduler og behandles én gang.` : ""}
            </p>
            {estimate.skipped.length ? (
              <Disclosure summary={`${estimate.skipped.length} side(r) kan ikke behandles`}>
                <ul className="ek-stack" data-gap="1">
                  {estimate.skipped.map((s) => <li key={s.title + s.reason} className="ek-small"><strong>{s.title}</strong>: {s.reason}</li>)}
                </ul>
              </Disclosure>
            ) : null}
            {!estimate.available ? <Alert tone="warning" title="Kan ikke starte">{estimate.reason}</Alert> : null}
            <Alert tone={estimate.external ? "warning" : "info"} title="Dette sendes">
              {estimate.payload_short || estimate.payload_summary}
            </Alert>
            <Disclosure summary="Avanserte innstillinger: modeller og kostnadsanslag">
              <div className="ek-stack" data-gap="3">
                <ul className="ek-stack" data-gap="2">
                  {estimate.receivers.map((r) => (
                    <li key={r.role}><strong>{r.role}</strong> → {r.service}: <span className="ek-small">{r.content}</span></li>
                  ))}
                </ul>
                <DataTable caption="Kostnadsanslag" captionHidden columns={columns} rows={estimate.estimate.lines} rowKey={(l) => l.key} />
                <p className="ek-small">
                  Totalt anslått: {money(estimate.estimate.total_low, estimate.estimate.currency)} – {money(estimate.estimate.total_high, estimate.estimate.currency)}
                  {" "}for ca. {estimate.estimate.images_low}–{estimate.estimate.images_high} bilder.
                  {settings.cost_limit_usd !== null ? ` Kostnadsgrense: ${money(settings.cost_limit_usd)}.` : ""}
                </p>
                <p className="ek-small ek-muted">{estimate.estimate.note} {catalog.pricing.note}</p>
              </div>
            </Disclosure>
            <Checkbox label="Lag bildene rett etter analysen" hint="Ellers ser du bildeplanen først og lager bildene i neste steg."
              checked={generateNow} onChange={(e) => setGenerateNow(e.target.checked)} />
            {generateNow ? (
              <Checkbox label="Automatisk innsetting" hint="Unntaket fra at du godkjenner hvert bilde: bilder som består kvalitetskontrollen, settes inn i Canvas uten gjennomgang når du krysser av her. Bilder som må kontrolleres, venter alltid på deg. Alt går via endringskøen med sikkerhetskopi og angremulighet."
                checked={autoInsert} onChange={(e) => setAutoInsert(e.target.checked)} />
            ) : null}
            {generateNow && autoInsert && estimate.usage_rights_required ? (
              <SelectField label="Opphavsrettsgrunnlag for bildene" hint="Emnet krever opphavsrettsinformasjon for filer. Du må selv vurdere riktig grunnlag."
                value={rights} onChange={(e) => setRights(e.target.value)} placeholder="Velg grunnlag"
                options={catalog.usage_rights.map((u) => ({ value: u.id, label: u.label }))} />
            ) : null}
            {mustConsent ? (
              <Checkbox label="Jeg godkjenner at innholdet sendes som beskrevet" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            ) : null}
            {start.error ? <Alert tone="danger">{start.error instanceof ApiError ? start.error.message : "Kunne ikke starte."}</Alert> : null}
            <div>
              <Button variant="primary" size="lg" icon={<Wand2 aria-hidden="true" />} disabled={!canStart} loading={start.isPending}
                onClick={() => start.mutate()}>
                {generateNow ? "Analyser og lag illustrasjoner" : "Analyser og foreslå bilder"}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

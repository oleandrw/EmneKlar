// Step 4 – Analyser innhold: estimate (Canvas only, no AI), what is sent where, consent, then the background job.
import { useMutation } from "@tanstack/react-query";
import { Calculator, ClipboardList, Copy, EyeOff, FileText, Layers, Wand2 } from "lucide-react";
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
  type Column,
} from "../../../design-system";
import { JobRunner } from "../../analysis/JobRunner";
import { money, type Catalog, type Estimate, type EstimateLine, type IllustrationSettings, type RunSummary, type Scope } from "./api";

export const JOB_WORDING = {
  noun: "jobben",
  current: "Nå behandles",
  findingsTitle: "Underveis",
  findingsEmpty: "Ingen resultater ennå.",
  cancelNote: "Det som allerede er analysert og laget, beholdes. Du kan fortsette senere.",
};

export function AnalyseStep({ courseId, scope, settings, catalog, busyJobId, onStarted, onDone }: {
  courseId: string;
  scope: Scope;
  settings: IllustrationSettings;
  catalog: Catalog;
  busyJobId: string | null;
  onStarted: (run: RunSummary, job: Job) => void;
  onDone: (job: Job) => void;
}) {
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [consent, setConsent] = useState(false);
  const [autoInsert, setAutoInsert] = useState(false);
  const [rights, setRights] = useState("");
  const [jobId, setJobId] = useState<string | null>(busyJobId);
  const body = { scope, settings };
  const calc = useMutation({
    mutationFn: () => api.post<Estimate>(`/api/courses/${courseId}/illustrations/estimate`, { ...body, mode: "full" }),
    onSuccess: (e) => {
      setEstimate(e);
      setConsent(false);
    },
  });
  const start = useMutation({
    mutationFn: (mode: "full" | "plan") => api.post<{ run: RunSummary; job: Job }>(`/api/courses/${courseId}/illustrations/runs`, {
      ...body, mode, auto_insert: mode === "full" && autoInsert, confirmed: true,
      usage_rights: rights ? { use_justification: rights } : null,
    }),
    onSuccess: (r) => {
      setJobId(r.job.id);
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
  const rightsMissing = Boolean(estimate?.usage_rights_required && autoInsert && !rights);
  const canStart = Boolean(estimate?.available) && (!mustConsent || consent) && !rightsMissing && !start.isPending;

  if (jobId) {
    return (
      <Card title="4. Analyser innhold" description="Jobben kjører i bakgrunnen, også om du går til en annen side i EmneKlar. Fremdriften vises per modul og side.">
        <JobRunner jobId={jobId} wording={JOB_WORDING} onDone={(job) => onDone(job)} />
      </Card>
    );
  }
  return (
    <Card title="4. Analyser innhold" description="Først kartlegges emnet i Canvas (ingen KI). Deretter ser du hva som sendes hvor, og et kostnadsanslag, før noe sendes.">
      <div className="ek-stack" data-gap="6">
        <div>
          <Button icon={<Calculator aria-hidden="true" />} onClick={() => calc.mutate()} loading={calc.isPending}>
            {estimate ? "Beregn på nytt" : "Kartlegg og beregn"}
          </Button>
        </div>
        {calc.error ? <Alert tone="danger" title="Kunne ikke kartlegge emnet">{calc.error.message}</Alert> : null}
        {estimate ? (
          <div className="ek-stack" data-gap="6">
            <KeyFigureList label="Kartlegging">
              <KeyFigure icon={<Layers />} tone="info" value={estimate.stats.modules_in_scope} label="Moduler" />
              <KeyFigure icon={<FileText />} tone="info" value={estimate.stats.pages_in_scope} label="Sider som analyseres" />
              <KeyFigure icon={<Copy />} value={estimate.stats.pages_in_several_modules} label="Sider i flere moduler (behandles én gang)" />
              <KeyFigure icon={<EyeOff />} value={estimate.stats.unpublished_pages} label="Upubliserte sider" />
            </KeyFigureList>
            {estimate.limitations.map((l) => <p key={l} className="ek-small ek-muted">{l}</p>)}
            {estimate.skipped.length ? (
              <Disclosure summary={`${estimate.skipped.length} side(r) kan ikke behandles`}>
                <ul className="ek-stack" data-gap="1">
                  {estimate.skipped.map((s) => <li key={s.title + s.reason} className="ek-small"><strong>{s.title}</strong>: {s.reason}</li>)}
                </ul>
              </Disclosure>
            ) : null}
            {!estimate.available ? <Alert tone="warning" title="Kan ikke starte">{estimate.reason}</Alert> : null}
            <div className="ek-stack" data-gap="2">
              <h3>Kostnadsanslag</h3>
              <DataTable caption="Kostnadsanslag" captionHidden columns={columns} rows={estimate.estimate.lines} rowKey={(l) => l.key} />
              <p>
                <strong>Totalt anslått: {money(estimate.estimate.total_low, estimate.estimate.currency)} – {money(estimate.estimate.total_high, estimate.estimate.currency)}</strong>
                {" "}for ca. {estimate.estimate.images_low}–{estimate.estimate.images_high} bilder.
                {estimate.estimate.cached_pages ? ` ${estimate.estimate.cached_pages} side(r) er analysert før og brukes på nytt.` : ""}
              </p>
              <p className="ek-small ek-muted">{estimate.estimate.note} {catalog.pricing.note}</p>
              {estimate.estimate.unpriced.length ? <p className="ek-small">Uten prisanslag: {estimate.estimate.unpriced.join(", ")}.</p> : null}
              {settings.cost_limit_usd !== null ? <p className="ek-small">Kostnadsgrense for jobben: {money(settings.cost_limit_usd)}.</p> : null}
            </div>
            <div className="ek-stack" data-gap="2">
              <h3>Hva sendes hvor</h3>
              <ul className="ek-stack" data-gap="2">
                {estimate.receivers.map((r) => (
                  <li key={r.role}><strong>{r.role}</strong> → {r.service}: <span className="ek-small">{r.content}</span></li>
                ))}
              </ul>
              <p className="ek-small ek-muted">
                Sendes aldri: studentbesvarelser, karakterer, meldinger, diskusjonssvar, deltakerlister eller kontaktinformasjon. Tekst i emnet behandles
                som data – instruksjoner som står i fagstoffet, følges ikke.
              </p>
            </div>
            <Checkbox label="Automatisk innsetting" hint="Godkjente bilder settes inn i Canvas uten gjennomgang – bare bilder som besto kvalitetskontrollen. Bilder som må kontrolleres manuelt, venter alltid på deg. Alt går via endringskøen med sikkerhetskopi og angremulighet."
              checked={autoInsert} onChange={(e) => setAutoInsert(e.target.checked)} />
            {autoInsert && estimate.usage_rights_required ? (
              <SelectField label="Opphavsrettsgrunnlag for bildene" hint="Emnet krever opphavsrettsinformasjon for filer. Du må selv vurdere riktig grunnlag."
                value={rights} onChange={(e) => setRights(e.target.value)} placeholder="Velg grunnlag"
                options={catalog.usage_rights.map((u) => ({ value: u.id, label: u.label }))} />
            ) : null}
            {mustConsent ? (
              <Checkbox label="Jeg har sett hva som sendes, og godkjenner at innholdet sendes til tjenestene over"
                checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            ) : null}
            {start.error ? <Alert tone="danger">{start.error instanceof ApiError ? start.error.message : "Kunne ikke starte."}</Alert> : null}
            <div className="ek-cluster" data-gap="2">
              <Button variant="primary" size="lg" icon={<Wand2 aria-hidden="true" />} disabled={!canStart} loading={start.isPending && start.variables === "full"}
                onClick={() => start.mutate("full")}>
                Analyser og lag illustrasjoner
              </Button>
              <Button icon={<ClipboardList aria-hidden="true" />} disabled={!canStart} loading={start.isPending && start.variables === "plan"}
                onClick={() => start.mutate("plan")}>
                Bare lag bildeplan
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

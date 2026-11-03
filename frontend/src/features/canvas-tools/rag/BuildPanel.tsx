// Emne-RAG → «Opprett kunnskapsbase»: scope, a one-line summary of the sources («Tilpass kilder» opens the choices),
// the main button with one short note on content, KI and privacy («Les mer» has the details), the estimate when
// something must be approved, then a background job with real progress.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, RefreshCw, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { useState } from "react";

import { api } from "../../../core/api/client";
import { formatDurationRange, formatNumber } from "../../../core/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  Disclosure,
  Fieldset,
  RadioGroup,
  Spinner,
  useToast,
  type Column,
} from "../../../design-system";
import { JobRunner } from "../../analysis/JobRunner";
import type { JobWording } from "../../analysis/ProgressPanel";
import type { ContentIndex } from "../shared";
import {
  DEFAULT_OPTIONS,
  effectiveOptions,
  formatMb,
  KIND_ORDER,
  sourceSummary,
  type BuildOptions,
  type Estimate,
  type RagStatus,
} from "./api";
import { SourcesDrawer, type SourcesDraft } from "./SourcesDrawer";
import { sameTranscription, transcriptionOf, type TranscriptionValue } from "./TranscriptionFields";

type Mode = "update" | "full";

const WORDING: JobWording = {
  noun: "byggingen",
  current: "Nå behandles",
  findingsTitle: "I kunnskapsbasen",
  findingsEmpty: "Ingen utdrag ennå.",
  cancelNote: "Det som allerede er ferdig, beholdes i kunnskapsbasen. Velg «Oppdater kunnskapsbasen» senere for å " +
    "fortsette der du slapp.",
  countOnly: "utdrag i kunnskapsbasen",
};

function optionsFrom(status: RagStatus): BuildOptions {
  return { ...DEFAULT_OPTIONS, ...(status.index?.options ?? {}) };
}

function EstimateView({ estimate, accept, setAccept, consent, setConsent }: {
  estimate: Estimate;
  accept: boolean;
  setAccept: (v: boolean) => void;
  consent: boolean;
  setConsent: (v: boolean) => void;
}) {
  const rows = KIND_ORDER.filter(([key]) => estimate.counts[key]).map(([key, label]) => ({ key, label,
    count: estimate.counts[key] }));
  const columns: Column<(typeof rows)[number]>[] = [
    { key: "label", header: "Innhold", rowHeader: true, cell: (r) => r.label },
    { key: "count", header: "Antall", numeric: true, cell: (r) => formatNumber(r.count) },
  ];
  const external = estimate.embedding.needs_confirmation || estimate.ai.some((a) => a.external && a.available);
  return (
    <section className="ek-stack" data-gap="4" aria-labelledby="rag-estimat">
      <h3 id="rag-estimat">Estimat</h3>
      <DataTable caption="Innhold som leses" columns={columns} rows={rows} rowKey={(r) => r.key}
        empty={estimate.unpublished ? "Fant ikke noe publisert innhold med disse valgene."
          : "Fant ikke noe innhold med disse valgene."} />
      {estimate.unpublished ? (
        <Alert tone={rows.length ? "info" : "warning"}
          title={`${formatNumber(estimate.unpublished)} upubliserte elementer er ikke med`}>
          For hele emnet tas upublisert innhold ikke med som standard. Slå på «Ta med upubliserte elementer» under
          «Tilpass kilder», eller velg modulene under «Valgte moduler», og prøv igjen.
        </Alert>
      ) : null}
      {estimate.unpublished_included ? (
        <Alert tone="info" title={`${formatNumber(estimate.unpublished_included)} upubliserte elementer er med`}>
          De er ikke synlige for studentene i Canvas ennå. Ikke del kunnskapsbasen eller eksporten med studenter hvis den har
          innhold de ikke skal se (for eksempel eksamensoppgaver).
        </Alert>
      ) : null}
      <p className="ek-small">
        Omtrent {formatNumber(estimate.words)} ord tekst og {formatNumber(estimate.documents.count)} dokumenter
        ({formatMb(estimate.documents.size_mb)}), anslagsvis {formatNumber(estimate.chunks_estimate)} utdrag.
        {estimate.video ? ` Video og lyd: ${estimate.video.count} (${estimate.video.with_captions} med teksting, ` +
          `${estimate.video.to_transcribe} transkriberes ${estimate.video.transcription === "provider"
            ? "via KI-leverandør" : estimate.video.transcription === "off" ? "ikke (slått av)" : "lokalt"}, ` +
          `${estimate.video.youtube + estimate.video.vimeo} fra YouTube eller Vimeo der teksting hentes hvis den finnes, ` +
          `${estimate.video.unavailable} kan ikke leses). ` +
          `Kjent varighet: ca. ${Math.round(estimate.video.minutes_known)} minutter` +
          (estimate.video.unknown_duration ? `, ${estimate.video.unknown_duration} med ukjent varighet.` : ".") : ""}
        {estimate.images ? ` Bilder: ${estimate.images.candidates} kandidater (${estimate.images.documents_note}).` : ""}
      </p>
      <p>
        <strong>Omtrentlig tid: {formatDurationRange(estimate.time.low_seconds, estimate.time.high_seconds)}</strong>
      </p>
      <Disclosure summary="Slik er tiden beregnet">
        <ul className="ek-small">{estimate.time.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
      </Disclosure>
      {estimate.documents.too_large.length ? (
        <Alert tone="warning" title="For store filer hoppes over">
          <ul>{estimate.documents.too_large.map((f) => <li key={f.title}>{f.title} ({formatMb(f.size_mb)})</li>)}</ul>
        </Alert>
      ) : null}
      {estimate.ai.length ? (
        <Card title="KI-bruk" headingLevel={4}>
          <ul className="ek-small">
            {estimate.ai.map((a) => (
              <li key={a.task}>
                {a.label}: {a.available
                  ? (a.minutes != null ? `ca. ${formatNumber(a.minutes)} minutter lyd i ${formatNumber(a.calls)} biter`
                    : `ca. ${formatNumber(a.calls)} kall og ${formatNumber(a.input_tokens)} tokens inn`) +
                    (a.route ? ` med ${a.route.model} (${a.route.provider})` : "")
                  : `ikke tilgjengelig – ${a.reason ?? ""}`}
              </li>
            ))}
          </ul>
          <p className="ek-xs ek-muted">EmneKlar lagrer ikke priser. Kostnaden avhenger av leverandørens priser for modellen.</p>
        </Card>
      ) : null}
      {estimate.downloads.length ? (
        <Alert tone="info" title="Lokale modeller lastes ned første gang">
          <ul>{estimate.downloads.map((d) => <li key={d.label}>{d.label}: ca. {formatMb(d.size_mb)}</li>)}</ul>
          <Checkbox label={`Jeg godtar nedlasting (til sammen ca. ${formatMb(estimate.downloads.reduce((s, d) => s + d.size_mb, 0))})`}
            checked={accept} onChange={(e) => setAccept(e.target.checked)} />
        </Alert>
      ) : null}
      <Alert tone={external ? "warning" : "info"} title="Personvern">
        <ul>{estimate.privacy.map((p) => <li key={p}>{p}</li>)}</ul>
        {external ? (
          <Checkbox label="Jeg har sett hva som sendes til den eksterne KI-leverandøren" checked={consent}
            onChange={(e) => setConsent(e.target.checked)} />
        ) : null}
      </Alert>
      {estimate.limitations.length ? (
        <Alert tone="warning" title="Begrensninger"><ul>{estimate.limitations.map((l) => <li key={l}>{l}</li>)}</ul></Alert>
      ) : null}
      {estimate.skipped.length ? (
        <Disclosure summary={`${estimate.skipped.length} elementer blir ikke med`}>
          <ul className="ek-small">
            {estimate.skipped.map((s) => <li key={s.key}><strong>{s.title}</strong> ({s.kind_label}): {s.reason}</li>)}
          </ul>
        </Disclosure>
      ) : null}
    </section>
  );
}

/** The one note on content, KI and privacy, by the main button; the details are behind «Les mer». */
function PrivacySummary({ status }: { status: RagStatus }) {
  const rag = status.settings;
  const provider = status.providers.find((p) => p.id === rag.transcription_provider_id)?.name ?? rag.transcription_provider_id;
  const search = !status.embedding.available ? "Søket bruker nøkkelord og kjører på denne maskinen."
    : status.embedding.external
      ? `Søket bruker ${status.embedding.label} hos en ekstern leverandør; utdragene sendes dit først når du har godkjent det.`
      : `Søket (${status.embedding.label}) kjører på denne maskinen.`;
  const transcription = rag.transcription === "provider"
    ? `Video uten teksting transkriberes av ${provider}: bare lyden sendes, i biter, og bare etter at du har godkjent det.`
    : rag.transcription === "off" ? "Video uten teksting transkriberes ikke; bare eksisterende teksting brukes."
      : "Video uten teksting transkriberes på denne maskinen med NB-Whisper.";
  const online = [rag.youtube_captions && "YouTube", rag.vimeo_captions && "Vimeo"].filter(Boolean).join(" og ");
  return (
    <div className="ek-stack" data-gap="1">
      <p className="ek-small ek-muted ek-icon-text">
        <ShieldCheck aria-hidden="true" />
        <span>
          Bare lærerens innhold brukes, og kunnskapsbasen lagres bare på denne maskinen. Skal noe lastes ned eller
          sendes til en KI-leverandør, ser du hva og godkjenner det først.
        </span>
      </p>
      <Disclosure summary="Les mer om innhold, KI og personvern">
        <ul className="ek-small">
          <li>
            Leses: sider, oppgave- og quizbeskrivelser, emneplanen, diskusjonsinnlegg skrevet av lærere og filer lastet
            opp av lærere. Video fra emnets medieliste tas bare med når lærerens innhold peker på den (listen kan ha
            studentopptak).
          </li>
          <li>Leses aldri: innleveringer, karakterer, meldinger, studentenes innlegg og svar i diskusjoner.</li>
          <li>Ingenting endres i Canvas.</li>
          <li>{search}</li>
          <li>{transcription}</li>
          {online ? (
            <li>Fra {online} hentes bare teksting (video-id-en sendes); lyd derfra lastes aldri ned.</li>
          ) : null}
          <li>
            KI brukes bare til det du har valgt: bildebeskrivelser, kontekstuell berikelse, svar under «Spør emnet» og
            testspørsmål til kvalitetsmålingen. Svar fra KI merkes som KI-forslag som må vurderes.
          </li>
        </ul>
      </Disclosure>
    </div>
  );
}

function needsReview(estimate: Estimate): boolean {
  const external = estimate.embedding.needs_confirmation || estimate.ai.some((a) => a.external && a.available);
  const empty = !Object.values(estimate.counts).some((n) => n > 0);
  return external || empty || estimate.downloads.length > 0 || estimate.unpublished > 0 ||
    estimate.unpublished_included > 0;
}

export function BuildPanel({ courseId, status }: { courseId: string; status: RagStatus }) {
  const client = useQueryClient();
  const toast = useToast();
  const [options, setOptions] = useState<BuildOptions>(() => optionsFrom(status));
  const [draft, setDraft] = useState<SourcesDraft | null>(null);
  const [estimated, setEstimated] = useState<{ key: string; mode: Mode; data: Estimate } | null>(null);
  const [accept, setAccept] = useState(false);
  const [consent, setConsent] = useState(false);
  const [jobId, setJobId] = useState<string | null>(status.busy_job);
  const index = useQuery({
    queryKey: ["content-index", courseId],
    queryFn: () => api.get<ContentIndex>(`/api/courses/${courseId}/content-index`),
    enabled: options.scope === "modules",
  });
  const set = (patch: Partial<BuildOptions>) => setOptions((o) => ({ ...o, ...patch }));
  const sent = effectiveOptions(options, status);
  const key = JSON.stringify(sent);
  const estimate = estimated?.key === key ? estimated.data : null;
  const summary = sourceSummary(options, status);
  const start = useMutation({
    mutationFn: ({ mode, confirmed, downloads }: { mode: Mode; confirmed: boolean; downloads: boolean }) =>
      api.post<{ id: string }>(`/api/courses/${courseId}/rag/build`, { ...sent, mode, accept_downloads: downloads,
        confirmed }),
    onSuccess: (job) => setJobId(job.id),
  });
  const runEstimate = useMutation({
    mutationFn: async (mode: Mode) => ({ key, mode,
      data: await api.post<Estimate>(`/api/courses/${courseId}/rag/estimate`, sent) }),
    onSuccess: (result) => {
      setEstimated(result);
      setAccept(false);
      setConsent(false);
      // Nothing to approve or look at: go straight on (the progress view shows what happens).
      if (!needsReview(result.data)) start.mutate({ mode: result.mode, confirmed: false, downloads: false });
    },
  });
  const saveTranscription = useMutation({
    mutationFn: (value: TranscriptionValue) => api.patch(`/api/settings/rag`, value),
  });
  const apply = async () => {
    if (!draft) return;
    if (!sameTranscription(draft.transcription, transcriptionOf(status.settings))) {
      await saveTranscription.mutateAsync(draft.transcription);
      await client.invalidateQueries({ queryKey: ["rag", courseId] });
    }
    setOptions(draft.options);
    setDraft(null);
  };
  const exists = Boolean(status.index);
  const needsAccept = Boolean(estimate?.downloads.length) && !accept;
  const external = Boolean(estimate && (estimate.embedding.needs_confirmation ||
    estimate.ai.some((a) => a.external && a.available)));
  const empty = Boolean(estimate) && !Object.values(estimate?.counts ?? {}).some((n) => n > 0);
  const blocked = !estimate || empty || needsAccept || (external && !consent);
  const noModules = options.scope === "modules" && options.module_ids.length === 0;

  if (jobId) {
    return (
      <Card title={status.index ? "Oppdaterer kunnskapsbasen" : "Oppretter kunnskapsbasen"} headingLevel={2}>
        <JobRunner jobId={jobId} wording={WORDING} onDone={(job) => {
          void client.invalidateQueries({ queryKey: ["rag", courseId] });
          if (job.status === "completed") {
            const r = job.result as { chunks?: number; skipped_total?: number; items_processed?: number; unchanged?: number;
              kept?: number };
            toast.show({ tone: "success", title: "Kunnskapsbasen er klar",
              body: `${r.chunks ?? 0} utdrag. ${r.items_processed ?? 0} elementer behandlet, ${r.unchanged ?? 0} uendret, ` +
                (r.kept ? `${r.kept} beholdt fra forrige versjon (prøves igjen neste gang), ` : "") +
                `${r.skipped_total ?? 0} hoppet over.` });
          }
        }} />
        <div className="ek-cluster ek-mt-4">
          <Button onClick={() => { setJobId(null); setEstimated(null); }}>Tilbake til valgene</Button>
        </div>
      </Card>
    );
  }

  const buildLabel = exists ? "Oppdater kunnskapsbasen" : "Opprett kunnskapsbase";
  return (
    <div className="ek-stack" data-gap="6">
      <Card title="Hva skal med?" headingLevel={2}>
        <div className="ek-stack" data-gap="6">
          <RadioGroup legend="Omfang" name="rag-scope" value={options.scope} onChange={(scope) => set({ scope })}
            options={[
              { value: "course", label: "Hele emnet", hint: "Alt lærerinnhold, også det som ikke ligger i moduler." },
              { value: "modules", label: "Valgte moduler",
                hint: "Alt i modulene du velger og filene de lenker til – også det som ikke er publisert ennå." },
            ]} />
          {options.scope === "modules" ? (
            index.isPending ? <Spinner label="Henter moduler …" /> : (
              <Fieldset legend="Moduler">
                {(index.data?.modules ?? []).map((m) => (
                  <Checkbox key={m.id} label={`${m.name} (${m.items_count} elementer${m.published === false ? ", upublisert" : ""})`}
                    checked={options.module_ids.includes(m.id)}
                    onChange={(e) => set({ module_ids: e.target.checked ? [...options.module_ids, m.id]
                      : options.module_ids.filter((x) => x !== m.id) })} />
                ))}
              </Fieldset>
            )
          ) : null}
          <section className="ek-stack" data-gap="2" aria-labelledby="rag-kilder">
            <h3 id="rag-kilder" className="ek-small">Kilder</h3>
            <p>{summary.text}</p>
            {summary.notes.map((note) => <p key={note} className="ek-small ek-muted">{note}</p>)}
            <div className="ek-cluster">
              <Button icon={<SlidersHorizontal aria-hidden="true" />}
                onClick={() => setDraft({ options, transcription: transcriptionOf(status.settings) })}>
                Tilpass kilder
              </Button>
            </div>
          </section>
          <div className="ek-stack" data-gap="3">
            <div className="ek-cluster">
              <Button variant="primary" size="lg" icon={<Play aria-hidden="true" />} onClick={() => runEstimate.mutate("update")}
                loading={(runEstimate.isPending && runEstimate.variables === "update") || start.isPending}
                disabled={noModules || summary.nothing}>
                {buildLabel}
              </Button>
              {exists ? (
                <Button size="lg" icon={<RefreshCw aria-hidden="true" />} onClick={() => runEstimate.mutate("full")}
                  loading={runEstimate.isPending && runEstimate.variables === "full"} disabled={noModules || summary.nothing}>
                  Bygg på nytt fra bunnen av
                </Button>
              ) : null}
            </div>
            {noModules ? <p className="ek-small ek-muted">Velg minst én modul.</p> : null}
            {exists ? (
              <p className="ek-small ek-muted">
                Oppdateringen behandler bare nye og endrede elementer og fjerner det som er slettet i Canvas.
              </p>
            ) : null}
            <PrivacySummary status={status} />
          </div>
          {runEstimate.error ? <Alert tone="danger" role="alert">{(runEstimate.error as Error).message}</Alert> : null}
          {start.error && !estimate ? <Alert tone="danger" role="alert">{(start.error as Error).message}</Alert> : null}
        </div>
      </Card>

      <SourcesDrawer status={status} draft={draft} onChange={setDraft} onCancel={() => setDraft(null)}
        onApply={() => { void apply(); }} saving={saveTranscription.isPending}
        error={saveTranscription.error ? (saveTranscription.error as Error).message : null} />

      {estimate && estimated && needsReview(estimate) ? (
        <Card headingLevel={2} title="Før du bygger"
          actions={status.embedding.available ? <Badge tone="success">Semantisk søk</Badge> : <Badge>Bare nøkkelordsøk</Badge>}>
          <div className="ek-stack" data-gap="4">
            {!status.embedding.available && status.embedding.reason ? (
              <Alert tone="info">{status.embedding.reason}</Alert>
            ) : null}
            <EstimateView estimate={estimate} accept={accept} setAccept={setAccept} consent={consent} setConsent={setConsent} />
            <div className="ek-cluster">
              <Button variant="primary" icon={<Play aria-hidden="true" />}
                onClick={() => start.mutate({ mode: estimated.mode, confirmed: consent, downloads: accept })}
                loading={start.isPending} disabled={blocked}>
                {estimated.mode === "full" ? "Start bygging fra bunnen av" : exists ? "Start oppdatering" : "Start bygging"}
              </Button>
              <Button onClick={() => setEstimated(null)}>Endre valg</Button>
            </div>
            {start.error ? <Alert tone="danger" role="alert">{(start.error as Error).message}</Alert> : null}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

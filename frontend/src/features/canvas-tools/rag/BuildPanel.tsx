// Emne-RAG → Bygg indeks: scope, source types, estimate, then a background job with real progress.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calculator, Play, RefreshCw } from "lucide-react";
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
  formatMb,
  KIND_ORDER,
  type BuildOptions,
  type Estimate,
  type FileGroup,
  type RagStatus,
} from "./api";

const WORDING: JobWording = {
  noun: "byggingen",
  current: "Nå behandles",
  findingsTitle: "I indeksen",
  findingsEmpty: "Ingen utdrag ennå.",
  cancelNote: "Det som allerede er ferdig, beholdes i indeksen. Velg «Oppdater indeks» senere for å fortsette der du slapp.",
  countOnly: "utdrag i indeksen",
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
        empty="Fant ikke noe innhold med disse valgene." />
      <p className="ek-small">
        Omtrent {formatNumber(estimate.words)} ord tekst og {formatNumber(estimate.documents.count)} dokumenter
        ({formatMb(estimate.documents.size_mb)}), anslagsvis {formatNumber(estimate.chunks_estimate)} utdrag.
        {estimate.video ? ` Video og lyd: ${estimate.video.count} (${estimate.video.with_captions} med teksting, ` +
          `${estimate.video.to_transcribe} transkriberes lokalt, ${estimate.video.unavailable} kan ikke leses). ` +
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

export function BuildPanel({ courseId, status }: { courseId: string; status: RagStatus }) {
  const client = useQueryClient();
  const toast = useToast();
  const [options, setOptions] = useState<BuildOptions>(() => optionsFrom(status));
  const [estimated, setEstimated] = useState<{ key: string; data: Estimate } | null>(null);
  const [accept, setAccept] = useState(false);
  const [consent, setConsent] = useState(false);
  const [jobId, setJobId] = useState<string | null>(status.busy_job);
  const index = useQuery({
    queryKey: ["content-index", courseId],
    queryFn: () => api.get<ContentIndex>(`/api/courses/${courseId}/content-index`),
    enabled: options.scope === "modules",
  });
  const set = (patch: Partial<BuildOptions>) => setOptions((o) => ({ ...o, ...patch }));
  const key = JSON.stringify(options);
  const estimate = estimated?.key === key ? estimated.data : null;
  const runEstimate = useMutation({
    mutationFn: async () => ({ key, data: await api.post<Estimate>(`/api/courses/${courseId}/rag/estimate`, options) }),
    onSuccess: setEstimated,
  });
  const start = useMutation({
    mutationFn: (mode: "update" | "full") => api.post<{ id: string }>(`/api/courses/${courseId}/rag/build`, {
      ...options, mode, accept_downloads: accept, confirmed: consent }),
    onSuccess: (job) => setJobId(job.id),
  });
  const exists = Boolean(status.index);
  const needsAccept = Boolean(estimate?.downloads.length) && !accept;
  const external = Boolean(estimate && (estimate.embedding.needs_confirmation ||
    estimate.ai.some((a) => a.external && a.available)));
  const blocked = !estimate || needsAccept || (external && !consent);
  const unavailable = status.not_available;
  const toggleGroup = (group: FileGroup, on: boolean) =>
    set({ file_groups: on ? [...options.file_groups, group] : options.file_groups.filter((g) => g !== group) });

  if (jobId) {
    return (
      <Card title="Bygger indeksen" headingLevel={2}>
        <JobRunner jobId={jobId} wording={WORDING} onDone={(job) => {
          void client.invalidateQueries({ queryKey: ["rag", courseId] });
          if (job.status === "completed") {
            const r = job.result as { chunks?: number; skipped_total?: number; items_processed?: number; unchanged?: number };
            toast.show({ tone: "success", title: "Indeksen er klar",
              body: `${r.chunks ?? 0} utdrag. ${r.items_processed ?? 0} elementer behandlet, ${r.unchanged ?? 0} uendret, ` +
                `${r.skipped_total ?? 0} hoppet over.` });
          }
        }} />
        <div className="ek-cluster ek-mt-4">
          <Button onClick={() => { setJobId(null); setEstimated(null); }}>Tilbake til valgene</Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="ek-stack" data-gap="6">
      <Card title="Hva skal med?" headingLevel={2}>
        <div className="ek-stack" data-gap="6">
          <RadioGroup legend="Omfang" name="rag-scope" value={options.scope} onChange={(scope) => set({ scope })}
            options={[
              { value: "course", label: "Hele emnet", hint: "Alt lærerinnhold, også det som ikke ligger i moduler." },
              { value: "modules", label: "Valgte moduler", hint: "Elementene i modulene og filene de lenker til." },
            ]} />
          {options.scope === "modules" ? (
            index.isPending ? <Spinner label="Henter moduler …" /> : (
              <Fieldset legend="Moduler">
                {(index.data?.modules ?? []).map((m) => (
                  <Checkbox key={m.id} label={`${m.name} (${m.items_count} elementer)`} checked={options.module_ids.includes(m.id)}
                    onChange={(e) => set({ module_ids: e.target.checked ? [...options.module_ids, m.id]
                      : options.module_ids.filter((x) => x !== m.id) })} />
                ))}
              </Fieldset>
            )
          ) : null}
          <Fieldset legend="Kildetyper">
            <Checkbox label="Tekst fra Canvas" checked={options.text} onChange={(e) => set({ text: e.target.checked })}
              hint="Sider, oppgave- og quizbeskrivelser, emneplan og lærerens diskusjonsinnlegg." />
            <Checkbox label="Dokumenter" checked={options.documents} onChange={(e) => set({ documents: e.target.checked })}
              hint="Filer i emnet. Tabeller blir egne utdrag, og lysbilder ett utdrag hver med notater." />
            {options.documents ? (
              <Fieldset legend="Filtyper">
                {status.file_groups.map((g) => (
                  <Checkbox key={g.key} label={g.label} checked={options.file_groups.includes(g.key)}
                    onChange={(e) => toggleGroup(g.key, e.target.checked)} />
                ))}
              </Fieldset>
            ) : null}
            <Checkbox label="Video og lyd" checked={options.video} disabled={Boolean(unavailable.video)}
              onChange={(e) => set({ video: e.target.checked })}
              hint={unavailable.video ?? (status.transcription.mode === "provider"
                ? "Eksisterende teksting først, ellers transkripsjon via KI-leverandør (bare lyden sendes)."
                : status.transcription.mode === "off" ? "Bare eksisterende teksting – transkripsjon er slått av."
                  : "Eksisterende teksting først, ellers lokal transkripsjon med NB-Whisper.")} />
            <Checkbox label="Bilder" checked={options.images} disabled={Boolean(unavailable.images)}
              onChange={(e) => set({ images: e.target.checked })}
              hint={unavailable.images ?? "Beskrivelser med en bildemodell (KI). Pynt, ikoner og duplikater filtreres bort."} />
          </Fieldset>
          <Fieldset legend="Valg">
            <Checkbox label="Ta med upubliserte elementer" checked={options.include_unpublished}
              onChange={(e) => set({ include_unpublished: e.target.checked })}
              hint="Av som standard. Slå på bare hvis indeksen ikke skal deles med studenter." />
            <Checkbox label="Kontekstuell berikelse med KI" checked={options.contextual_enrichment}
              disabled={Boolean(unavailable.contextual_enrichment)}
              onChange={(e) => set({ contextual_enrichment: e.target.checked })}
              hint={unavailable.contextual_enrichment ?? "En til to setninger foran hvert utdrag som sier hvor det hører hjemme. Gir bedre treff, men krever KI."} />
            {options.video ? (
              <Checkbox label="Nøkkelbilder fra video (lysbilder i opptak)" checked={options.keyframes}
                disabled={Boolean(unavailable.keyframes)} onChange={(e) => set({ keyframes: e.target.checked })}
                hint={unavailable.keyframes ?? "Av som standard. Bilder ved sceneskifte beskrives med bildemodellen og kobles til tidspunktet."} />
            ) : null}
          </Fieldset>
          <div className="ek-cluster">
            <Button icon={<Calculator aria-hidden="true" />} onClick={() => runEstimate.mutate()} loading={runEstimate.isPending}
              disabled={options.scope === "modules" && options.module_ids.length === 0}>
              Beregn estimat
            </Button>
          </div>
          {runEstimate.error ? <Alert tone="danger" role="alert">{(runEstimate.error as Error).message}</Alert> : null}
        </div>
      </Card>

      {estimate ? (
        <Card headingLevel={2} title="Klar til å bygge"
          actions={status.embedding.available ? <Badge tone="success">Semantisk søk</Badge> : <Badge>Bare nøkkelordsøk</Badge>}>
          <div className="ek-stack" data-gap="4">
            {!status.embedding.available && status.embedding.reason ? (
              <Alert tone="info">{status.embedding.reason}</Alert>
            ) : null}
            <EstimateView estimate={estimate} accept={accept} setAccept={setAccept} consent={consent} setConsent={setConsent} />
            <div className="ek-cluster">
              <Button variant="primary" icon={<Play aria-hidden="true" />} onClick={() => start.mutate("update")}
                loading={start.isPending} disabled={blocked}>
                {exists ? "Oppdater indeks" : "Bygg indeks"}
              </Button>
              {exists ? (
                <Button icon={<RefreshCw aria-hidden="true" />} onClick={() => start.mutate("full")} disabled={blocked}>
                  Bygg på nytt fra bunnen av
                </Button>
              ) : null}
            </div>
            {exists ? (
              <p className="ek-small ek-muted">
                «Oppdater indeks» behandler bare nye og endrede elementer og fjerner det som er slettet i Canvas.
              </p>
            ) : null}
            {start.error ? <Alert tone="danger" role="alert">{(start.error as Error).message}</Alert> : null}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

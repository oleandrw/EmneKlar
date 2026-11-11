// Media findings: what the recording is (and what that is based on), hints about a text alternative near it, and the
// teacher's confirmation («Kontrollert»). The requirement depends on the kind: audio only → a text alternative
// (WCAG 1.2.1), video with sound → captions (1.2.2), video without sound → a text or audio alternative (1.2.1).
// EmneKlar never decides by itself that a text near a recording is a full alternative – the teacher confirms.
import { useEffect, useRef, useState } from "react";

import type { Finding, MediaKind } from "../../core/api/types";
import { Alert, Button, KeyValue, RadioGroup, TextArea } from "../../design-system";
import { useCourseAnalysis } from "../../core/jobs";
import { FINAL_STATUSES, useJob } from "../analysis/useJob";
import { useFindingActions } from "./api";
import { JobInlineStatus } from "../analysis/JobRunner";

export const MEDIA_KIND_LABEL: Record<string, string> = {
  audio: "Lydopptak",
  video: "Video med lyd",
  video_no_audio: "Video uten lyd",
  unknown: "Ukjent medietype",
};

const KIND_OPTIONS: { value: MediaKind; label: string; hint: string }[] = [
  { value: "audio", label: "Lydopptak", hint: "Bare lyd. Krav: et tekstalternativ (transkripsjon) på siden eller via en tydelig lenke (WCAG 1.2.1)." },
  { value: "video", label: "Video med lyd", hint: "Bilde og lyd. Krav: teksting som følger lyden (WCAG 1.2.2)." },
  { value: "video_no_audio", label: "Video uten lyd", hint: "Bare bilde. Krav: et tekst- eller lydalternativ (WCAG 1.2.1) – teksting er ikke relevant." },
];

const str = (value: unknown) => (typeof value === "string" && value ? value : null);

/** What the recording is, what that is based on, and – for media rules – the choice to correct it. */
export function MediaKindSection({ finding }: { finding: Finding }) {
  const actions = useFindingActions();
  const evidence = finding.evidence ?? {};
  const kind = str(evidence.media_kind);
  const basis = str(evidence.kind_basis);
  const canChoose = Boolean(finding.rule?.media_kind_choice && str(evidence.media_key));
  const unknown = kind === "unknown";
  const [choosing, setChoosing] = useState(unknown);
  const [choice, setChoice] = useState<MediaKind>((kind && kind !== "unknown" ? kind : "audio") as MediaKind);
  const [jobId, setJobId] = useState<string | null>(null);
  const [savedOnly, setSavedOnly] = useState(false);
  const job = useJob(jobId);
  // Another analysis of the course runs: a new one would overlap (EmneKlar runs one analysis per course at a time).
  const { running } = useCourseAnalysis();
  const busy = Boolean(running && running.id !== jobId);
  const finished = job.data && FINAL_STATUSES.has(job.data.status) ? job.data : null;
  const refreshed = useRef<string | null>(null);
  const refresh = actions.refresh;

  useEffect(() => {
    // Once per finished re-analysis: the finding list then shows the requirement for the chosen kind.
    if (finished && refreshed.current !== finished.id) {
      refreshed.current = finished.id;
      refresh();
    }
  }, [finished, refresh]);

  if (!kind) return null;
  const save = (value: MediaKind | null) =>
    actions.mediaKind.mutate({ finding, kind: value }, {
      onSuccess: (started) => {
        if (started) setJobId(started.id);
        else setSavedOnly(true);
        refresh();
      },
    });

  return (
    <section className="ek-stack" data-gap="2" aria-labelledby={`medietype-${finding.id}`}>
      <h3 id={`medietype-${finding.id}`}>Medietype</h3>
      <KeyValue items={[["Opptaket er", MEDIA_KIND_LABEL[kind] ?? kind], ...(basis ? ([["Grunnlag", basis]] as [string, string][]) : [])]} />
      {finished ? (
        <Alert tone={finished.status === "completed" ? "success" : "warning"} role="status"
          title={finished.status === "completed" ? "Siden er analysert på nytt" : "Analysen ble ikke fullført"}>
          {finished.status === "completed"
            ? "Funnlisten viser nå kravet som gjelder for medietypen du valgte. Lukk dette vinduet for å se det."
            : "Valget er lagret og brukes ved neste analyse."}
        </Alert>
      ) : jobId && job.data ? (
        <JobInlineStatus job={job.data} noun="analysen" />
      ) : jobId ? (
        <p className="ek-small">Analyserer siden på nytt …</p>
      ) : savedOnly ? (
        <Alert tone="info" role="status" title="Valget er lagret">
          Emneplanen analyseres bare sammen med hele emnet. Kjør en ny analyse av hele emnet for å se riktig krav.
        </Alert>
      ) : canChoose && choosing ? (
        <div className="ek-stack" data-gap="2">
          <RadioGroup legend="Hva er opptaket?" name={`medietype-valg-${finding.id}`} value={choice} onChange={setChoice}
            hint="Spill av opptaket for å se om det har bilde og lyd. Valget lagres lokalt for dette opptaket og brukes i senere analyser."
            options={KIND_OPTIONS} />
          {actions.mediaKind.error ? (
            <Alert tone="danger" role="alert" title="Kunne ikke lagre">{actions.mediaKind.error.message}</Alert>
          ) : null}
          {busy ? (
            <p className="ek-small ek-muted" id={`analyse-pagar-${finding.id}`}>
              En analyse av emnet pågår. EmneKlar analyserer ett emne om gangen – du kan lagre valget når den er ferdig.
            </p>
          ) : null}
          <div className="ek-cluster">
            {!unknown ? <Button onClick={() => setChoosing(false)}>Avbryt</Button> : null}
            <Button variant="primary" loading={actions.mediaKind.isPending} onClick={() => save(choice)} disabled={busy}
              aria-describedby={busy ? `analyse-pagar-${finding.id}` : undefined}>
              Lagre og analyser siden på nytt
            </Button>
          </div>
        </div>
      ) : canChoose ? (
        <div className="ek-cluster">
          <Button size="sm" onClick={() => setChoosing(true)}>Feil medietype?</Button>
          {evidence.kind_source === "user" ? (
            <Button size="sm" variant="ghost" loading={actions.mediaKind.isPending} onClick={() => save(null)}>
              Bruk opplysningene fra Canvas
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** Texts near the recording that may be a transcript, or a label saying the recording reads out text on the page. */
export function TextAlternativeHints({ finding }: { finding: Finding }) {
  const evidence = finding.evidence ?? {};
  const candidates = Array.isArray(evidence.text_alternative_candidates) ? (evidence.text_alternative_candidates as string[]) : [];
  const hint = str(evidence.media_alternative_hint);
  if (!candidates.length && !hint) return null;
  return (
    <Alert tone="info" title="Mulig tekstalternativ ved opptaket">
      <div className="ek-stack" data-gap="2">
        {candidates.length ? (
          <>
            <ul className="ek-small">{candidates.map((c) => <li key={c}>{c}</li>)}</ul>
            <p className="ek-small">Kontroller at teksten gjengir hele opptaket – EmneKlar kan ikke avgjøre det.</p>
          </>
        ) : null}
        {hint ? (
          <p className="ek-small">
            Teksten «{hint}» kan tyde på at opptaket er en innlesing av tekst på siden. Bekreft unntaket bare hvis siden sier
            tydelig at opptaket gjengir teksten.
          </p>
        ) : null}
      </div>
    </Alert>
  );
}

/** The rule's confirmations that apply to this finding – one that depends on evidence (the exemption for older
 *  documents) only when the analysis found it. */
export function availableConfirmations(finding: Finding) {
  return (finding.rule?.confirmations ?? []).filter((c) => !c.requires_evidence || Boolean(finding.evidence?.[c.requires_evidence]));
}

/** «Kontrollert»: the teacher confirms what the manual check asks for. Survives re-analysis and is listed in reports. */
export function ConfirmSection({ finding, onDone, onClose }: { finding: Finding; onDone: () => void; onClose: () => void }) {
  const actions = useFindingActions();
  const confirmations = availableConfirmations(finding);
  const [choice, setChoice] = useState(confirmations[0]?.id ?? "");
  const [note, setNote] = useState("");
  if (!confirmations.length || finding.status === "fixed" || finding.status === "ignored") return null;
  if (finding.status === "verified") {
    return (
      <section className="ek-stack" data-gap="2" aria-labelledby={`kontrollert-${finding.id}`}>
        <h3 id={`kontrollert-${finding.id}`}>Kontrollert</h3>
        <Alert tone="success" title={finding.decision?.label ?? "Bekreftet etter kontroll"}>
          {finding.decision?.note ? <p className="ek-small">Merknad: {finding.decision.note}</p> : null}
          <p className="ek-small">Bekreftelsen gjelder også ved nye analyser og vises i rapporter.</p>
        </Alert>
        <div>
          <Button onClick={() => actions.reopen.mutate(finding.id, { onSuccess: onClose })} loading={actions.reopen.isPending}>
            Gjenåpne funnet
          </Button>
        </div>
      </section>
    );
  }
  return (
    <section className="ek-stack" data-gap="2" aria-labelledby={`bekreft-${finding.id}`}>
      <h3 id={`bekreft-${finding.id}`}>Bekreft etter kontroll</h3>
      <RadioGroup legend="Hva har du kontrollert?" name={`bekreft-${finding.id}`} value={choice} onChange={setChoice}
        options={confirmations.map((c) => ({ value: c.id, label: c.label, hint: c.hint }))} />
      <TextArea label="Merknad" optional value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000}
        hint={confirmations.find((c) => c.id === choice)?.requires_evidence
          ? "For eksempel hvorfor dokumentet ikke trengs i emnet nå. Lagres lokalt og vises i rapporter."
          : "For eksempel hvor transkripsjonen ligger. Lagres lokalt og vises i rapporter."} />
      {actions.verify.error ? <Alert tone="danger" role="alert" title="Kunne ikke lagre">{actions.verify.error.message}</Alert> : null}
      <p className="ek-xs ek-muted">EmneKlar kontrollerer ikke selv det du bekrefter. Funnet merkes «Kontrollert» og vises ikke blant åpne funn.</p>
      <div>
        <Button variant="primary" disabled={!choice} loading={actions.verify.isPending}
          onClick={() => actions.verify.mutate({ id: finding.id, confirmation: choice, note: note || undefined }, { onSuccess: onDone })}>
          Bekreft og merk som kontrollert
        </Button>
      </div>
    </section>
  );
}

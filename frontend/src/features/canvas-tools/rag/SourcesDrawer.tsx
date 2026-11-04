// Emne-RAG → «Opprett kunnskapsbase» → «Tilpass kilder»: the sources first; «Avansert» (closed) holds the KI add-ons
// and transcription. Settings appear only when they matter (file types with «Dokumenter», transcription with «Video og
// lyd», provider and model with an external service). Works on a draft: «Avbryt» discards it, «Lagre valg» saves the
// sources for this course and the transcription choice for all courses.
import { RotateCcw } from "lucide-react";

import { Alert, Button, Checkbox, Dialog, Disclosure, Fieldset } from "../../../design-system";
import { listNb, resetSources, type BuildOptions, type FileGroup, type RagStatus } from "./api";
import { CostBadge, TranscriptionFields, type TranscriptionValue } from "./TranscriptionFields";

export interface SourcesDraft {
  options: BuildOptions;
  transcription: TranscriptionValue;
}

function advancedSummary(draft: SourcesDraft, ai: boolean): string {
  const on = [
    ai && draft.options.contextual_enrichment && "kontekstuell berikelse",
    ai && draft.options.video && draft.options.keyframes && "nøkkelbilder",
    draft.options.video && draft.transcription.transcription === "provider" && "ekstern transkribering",
  ].filter((x): x is string => Boolean(x));
  return on.length ? `Avansert: KI og transkribering · ${listNb(on)} er på` : "Avansert: KI og transkribering";
}

export function SourcesDrawer({ status, draft, onChange, onCancel, onSave, saving, error }: {
  status: RagStatus;
  draft: SourcesDraft | null;
  onChange: (draft: SourcesDraft) => void;
  onCancel: () => void;
  onSave: () => void;
  saving: boolean;
  error: string | null;
}) {
  const options = draft?.options;
  const ai = status.ai.available;
  const needsAi = `Krever KI: ${status.ai.reason ?? "KI er ikke satt opp."}`;
  const set = (patch: Partial<BuildOptions>) => draft && onChange({ ...draft, options: { ...draft.options, ...patch } });
  const toggleGroup = (group: FileGroup, on: boolean) => options && set({
    file_groups: on ? [...options.file_groups, group] : options.file_groups.filter((g) => g !== group) });
  const nothing = Boolean(options && !(options.text || options.documents || options.video || (options.images && ai)));
  const noGroups = Boolean(options?.documents && options.file_groups.length === 0);
  return (
    <Dialog open={draft !== null} onClose={onCancel} variant="drawer" size="lg" title="Tilpass kilder"
      description="Velg hva som skal med i kunnskapsbasen." dismissible={!saving}
      footer={draft ? (
        <>
          <Button variant="ghost" icon={<RotateCcw aria-hidden="true" />} disabled={saving}
            onClick={() => onChange({ ...draft, options: resetSources(draft.options) })}>
            Tilbakestill kilder
          </Button>
          <Button onClick={onCancel} disabled={saving}>Avbryt</Button>
          <Button variant="primary" onClick={onSave} loading={saving} disabled={nothing || noGroups}>Lagre valg</Button>
        </>
      ) : null}>
      {draft && options ? (
        <div className="ek-stack" data-gap="6">
          <div className="ek-stack" data-gap="3">
            <Fieldset legend="Kilder" hint="Gjelder dette emnet.">
              <Checkbox label="Tekst fra Canvas" checked={options.text} onChange={(e) => set({ text: e.target.checked })}
                hint="Sider, oppgaver, quizer, emneplan og lærerens innlegg." />
              <Checkbox label="Dokumenter" checked={options.documents} onChange={(e) => set({ documents: e.target.checked })}
                hint="Filer lastet opp i emnet." />
              {options.documents ? (
                <Fieldset legend="Filtyper" nested>
                  {status.file_groups.map((g) => (
                    <Checkbox key={g.key} label={g.label} checked={options.file_groups.includes(g.key)}
                      onChange={(e) => toggleGroup(g.key, e.target.checked)} />
                  ))}
                </Fieldset>
              ) : null}
              <Checkbox label="Video og lyd" checked={options.video} disabled={Boolean(status.not_available.video)}
                onChange={(e) => set({ video: e.target.checked })}
                hint={status.not_available.video ?? "Bruker teksting når den finnes. Lyd uten teksting: se «Avansert»."} />
              <Checkbox label={<>Bildebeskrivelser med KI <CostBadge /></>} checked={options.images && ai}
                disabled={!ai || Boolean(status.not_available.images)} onChange={(e) => set({ images: e.target.checked })}
                hint={!ai ? needsAi : status.not_available.images ??
                  "KI beskriver bildene, så innholdet i dem blir søkbart. Alt-tekst er alltid med i sideteksten."} />
            </Fieldset>
            <Disclosure summary="Les mer om kildene">
              <ul className="ek-small">
                <li>Tabeller i dokumenter blir egne utdrag, og hvert lysbilde blir ett utdrag med notatene.</li>
                <li>
                  Teksting hentes fra Canvas, undertekstfiler, YouTube og Vimeo. Video fra emnets medieliste tas bare med
                  når lærerens innhold peker på den, og lyd fra YouTube og Vimeo lastes aldri ned.
                </li>
                <li>
                  Før bildene beskrives, filtreres pynt, ikoner, logoer og duplikater bort. Hvert bilde som beskrives,
                  er ett KI-kall, og beskrivelsen lagres så samme bilde ikke beskrives på nytt.
                </li>
              </ul>
            </Disclosure>
          </div>
          {nothing ? <Alert tone="warning">Velg minst én kilde.</Alert> : null}
          {noGroups ? <Alert tone="warning">Velg minst én filtype, eller slå av «Dokumenter».</Alert> : null}

          {options.scope === "course" ? (
            <Fieldset legend="Upublisert innhold">
              <Checkbox label="Ta med upubliserte elementer" checked={options.include_unpublished}
                onChange={(e) => set({ include_unpublished: e.target.checked })}
                hint="Av som standard. Ved valgte moduler tas alt i modulene med." />
            </Fieldset>
          ) : null}

          <Disclosure summary={advancedSummary(draft, ai)}>
            <div className="ek-stack" data-gap="6">
              <p className="ek-small">
                Valg merket «Kan koste ekstra» bruker en KI-leverandør. Du ser hva som sendes og godkjenner før noe starter.
              </p>
              <div className="ek-stack" data-gap="3">
                <Fieldset legend="KI-tillegg" hint="Gjelder dette emnet.">
                  <Checkbox label={<>Kontekstuell berikelse <CostBadge /></>} checked={options.contextual_enrichment && ai}
                    disabled={!ai || Boolean(status.not_available.contextual_enrichment)}
                    onChange={(e) => set({ contextual_enrichment: e.target.checked })}
                    hint={!ai ? needsAi : status.not_available.contextual_enrichment ??
                      "Bedre treff: hvert utdrag får en kort forklaring av hvor det hører hjemme."} />
                  {options.video ? (
                    <Checkbox label={<>Nøkkelbilder fra video <CostBadge /></>} checked={options.keyframes && ai}
                      disabled={!ai || Boolean(status.not_available.keyframes)}
                      onChange={(e) => set({ keyframes: e.target.checked })}
                      hint={!ai ? needsAi : status.not_available.keyframes ??
                        "Lysbilder i opptak beskrives og kobles til tidspunktet."} />
                  ) : null}
                </Fieldset>
                <Disclosure summary="Les mer om KI-tilleggene">
                  <ul className="ek-small">
                    <li>
                      Kontekstuell berikelse: ett KI-kall per åtte utdrag, med hele dokumentet som kontekst. Dokumentet
                      gjenbrukes med prompt caching, og resultatet lagres.
                    </li>
                    <li>Nøkkelbilder: bilder ved sceneskifte, opptil 30 per video, ett KI-kall per bilde.</li>
                  </ul>
                </Disclosure>
              </div>
              {options.video ? (
                <TranscriptionFields status={status} name="rag-transcription-build" value={draft.transcription}
                  onChange={(patch) => onChange({ ...draft, transcription: { ...draft.transcription, ...patch } })} />
              ) : null}
            </div>
          </Disclosure>
          {error ? <Alert tone="danger" role="alert">{error}</Alert> : null}
        </div>
      ) : null}
    </Dialog>
  );
}

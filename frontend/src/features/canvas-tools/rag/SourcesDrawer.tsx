// Emne-RAG → «Opprett kunnskapsbase» → «Tilpass kilder»: sources and file types, unpublished content, and an «Avansert» section
// with the choices that use KI or can cost money (contextual enrichment, keyframes, transcription service).
// Works on a draft: «Avbryt» discards it, «Bruk valgene» applies it (and saves the transcription service).
import { RotateCcw } from "lucide-react";

import { Alert, Button, Checkbox, Dialog, Fieldset } from "../../../design-system";
import { resetSources, type BuildOptions, type FileGroup, type RagStatus } from "./api";
import { TranscriptionFields, type TranscriptionValue } from "./TranscriptionFields";

export interface SourcesDraft {
  options: BuildOptions;
  transcription: TranscriptionValue;
}

export function SourcesDrawer({ status, draft, onChange, onCancel, onApply, saving, error }: {
  status: RagStatus;
  draft: SourcesDraft | null;
  onChange: (draft: SourcesDraft) => void;
  onCancel: () => void;
  onApply: () => void;
  saving: boolean;
  error: string | null;
}) {
  const options = draft?.options;
  const ai = status.ai.available;
  const aiReason = status.ai.reason ?? "KI er ikke satt opp.";
  const set = (patch: Partial<BuildOptions>) => draft && onChange({ ...draft, options: { ...draft.options, ...patch } });
  const toggleGroup = (group: FileGroup, on: boolean) => options && set({
    file_groups: on ? [...options.file_groups, group] : options.file_groups.filter((g) => g !== group) });
  const nothing = Boolean(options && !(options.text || options.documents || options.video || (options.images && ai)));
  const noGroups = Boolean(options?.documents && options.file_groups.length === 0);
  return (
    <Dialog open={draft !== null} onClose={onCancel} variant="drawer" size="lg" title="Tilpass kilder"
      description="Velg hva som skal leses inn. Alt er på som standard; KI-tillegg som kan koste penger, står under «Avansert»."
      dismissible={!saving}
      footer={draft ? (
        <>
          <Button variant="ghost" icon={<RotateCcw aria-hidden="true" />} disabled={saving}
            onClick={() => onChange({ ...draft, options: resetSources(draft.options) })}>
            Tilbakestill til standard
          </Button>
          <Button onClick={onCancel} disabled={saving}>Avbryt</Button>
          <Button variant="primary" onClick={onApply} loading={saving} disabled={nothing || noGroups}>Bruk valgene</Button>
        </>
      ) : null}>
      {draft && options ? (
        <div className="ek-stack" data-gap="6">
          <Fieldset legend="Kilder">
            <Checkbox label="Tekst fra Canvas" checked={options.text} onChange={(e) => set({ text: e.target.checked })}
              hint="Sider, oppgave- og quizbeskrivelser, emneplan og lærerens diskusjonsinnlegg." />
            <Checkbox label="Dokumenter" checked={options.documents} onChange={(e) => set({ documents: e.target.checked })}
              hint="Filer i emnet. Tabeller blir egne utdrag, og lysbilder ett utdrag hver med notater." />
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
              hint={status.not_available.video ?? ("Eksisterende teksting først (Canvas, undertekstfiler, YouTube, Vimeo). " +
                (draft.transcription.transcription === "provider"
                  ? "Uten teksting transkriberes lyden av KI-leverandøren (se «Avansert»)."
                  : draft.transcription.transcription === "off" ? "Uten teksting hoppes videoen over (se «Avansert»)."
                    : "Uten teksting transkriberes lyden lokalt med NB-Whisper (se «Avansert»)."))} />
            <Checkbox label="Bilder" checked={options.images && ai} disabled={!ai || Boolean(status.not_available.images)}
              onChange={(e) => set({ images: e.target.checked })}
              hint={!ai ? `Krever KI: ${aiReason}` : status.not_available.images ??
                "Bildene beskrives av bildemodellen i KI-oppsettet etter at pynt, ikoner og duplikater er filtrert " +
                "bort. Kan gi kostnad: ett KI-kall per bilde som beskrives (bufres, så samme bilde beskrives bare én gang)."} />
          </Fieldset>
          {nothing ? <Alert tone="warning">Velg minst én kilde.</Alert> : null}
          {noGroups ? <Alert tone="warning">Velg minst én filtype, eller slå av «Dokumenter».</Alert> : null}

          {options.scope === "course" ? (
            <Fieldset legend="Upublisert innhold">
              <Checkbox label="Ta med upubliserte elementer" checked={options.include_unpublished}
                onChange={(e) => set({ include_unpublished: e.target.checked })}
                hint="Av som standard for hele emnet. Velger du moduler, tas alt i dem med, publisert eller ikke." />
            </Fieldset>
          ) : null}

          <section className="ek-stack" data-gap="4" aria-labelledby="rag-avansert">
            <h3 id="rag-avansert">Avansert</h3>
            <p className="ek-small">
              Valgene her bruker KI eller en ekstern tjeneste og kan gi <strong>ekstra kostnad</strong> hos
              leverandøren. Estimatet viser antall kall, minutter lyd og hva som sendes før noe starter, og ingenting
              sendes uten at du godtar det. EmneKlar kjenner ikke leverandørens priser.
            </p>
            <Fieldset legend="KI-tillegg">
              <Checkbox label="Kontekstuell berikelse med KI" checked={options.contextual_enrichment && ai}
                disabled={!ai || Boolean(status.not_available.contextual_enrichment)}
                onChange={(e) => set({ contextual_enrichment: e.target.checked })}
                hint={!ai ? `Krever KI: ${aiReason}` : status.not_available.contextual_enrichment ??
                  "En til to setninger foran hvert utdrag som sier hvor det hører hjemme, så søket treffer bedre. " +
                  "Ekstra kostnad: ett KI-kall per åtte utdrag, med hele dokumentet som kontekst (gjenbrukes med " +
                  "prompt caching, og resultatet bufres)."} />
              <Checkbox label="Nøkkelbilder fra video (lysbilder i opptak)" checked={options.keyframes && options.video && ai}
                disabled={!ai || !options.video || Boolean(status.not_available.keyframes)}
                onChange={(e) => set({ keyframes: e.target.checked })}
                hint={!ai ? `Krever KI: ${aiReason}` : !options.video ? "Krever «Video og lyd»."
                  : status.not_available.keyframes ?? "Bilder ved sceneskifte beskrives av bildemodellen og kobles til " +
                    "tidspunktet. Ekstra kostnad: ett KI-kall per nøkkelbilde, opptil 30 per video."} />
            </Fieldset>
            <TranscriptionFields status={status} name="rag-transcription-build" value={draft.transcription}
              onChange={(patch) => onChange({ ...draft, transcription: { ...draft.transcription, ...patch } })} />
            <p className="ek-xs ek-muted">
              Transkripsjonstjenesten lagres som innstilling (også under «Innstillinger») og tilbakestilles ikke av
              «Tilbakestill til standard».
            </p>
          </section>
          {error ? <Alert tone="danger" role="alert">{error}</Alert> : null}
        </div>
      ) : null}
    </Dialog>
  );
}

// Emne-RAG: choice of transcription (used under «Tilpass kilder → Avansert» and under «Innstillinger»). A saved setting
// that applies to all courses. Provider, model and language appear only for an external service, with the privacy
// note right where that decision is made.
import { Alert, Badge, Disclosure, RadioGroup, SelectField, TextField } from "../../../design-system";
import type { RagSettings, RagStatus } from "./api";

export type TranscriptionValue = Pick<RagSettings, "transcription" | "transcription_provider_id" | "transcription_model"
  | "transcription_language">;

export function transcriptionOf(settings: RagSettings): TranscriptionValue {
  const { transcription, transcription_provider_id, transcription_model, transcription_language } = settings;
  return { transcription, transcription_provider_id, transcription_model, transcription_language };
}

export function sameTranscription(a: TranscriptionValue, b: TranscriptionValue): boolean {
  return a.transcription === b.transcription && a.transcription_provider_id === b.transcription_provider_id &&
    a.transcription_model === b.transcription_model && a.transcription_language === b.transcription_language;
}

// ISO 639-1 codes as the transcription API expects them; "" lets the service detect the language.
const LANGUAGES: [string, string][] = [["", "Oppdag automatisk"], ["no", "Norsk (bokmål)"], ["nn", "Norsk (nynorsk)"],
  ["en", "Engelsk"], ["sv", "Svensk"], ["da", "Dansk"], ["de", "Tysk"], ["fr", "Fransk"], ["es", "Spansk"]];

export function CostBadge() {
  return <Badge tone="warning">Kan koste ekstra</Badge>;
}

export function TranscriptionFields({ status, value, onChange, name }: {
  status: RagStatus;
  value: TranscriptionValue;
  onChange: (patch: Partial<TranscriptionValue>) => void;
  name: string;
}) {
  const providerType = status.providers.find((p) => p.id === value.transcription_provider_id)?.type ?? "";
  const models = status.transcription_models.filter((m) => m.provider_type === providerType);
  const plan = status.transcription.plan;
  const showPlan = value.transcription === "provider" && status.transcription.mode === "provider" &&
    status.settings.transcription_provider_id === value.transcription_provider_id;
  const languages = LANGUAGES.some(([code]) => code === value.transcription_language) ? LANGUAGES
    : [...LANGUAGES, [value.transcription_language, `Annet (${value.transcription_language})`] as [string, string]];
  return (
    <div className="ek-stack" data-gap="4">
      <RadioGroup legend="Lyd og video uten teksting" hint="Gjelder alle emner." name={name} value={value.transcription}
        onChange={(transcription) => onChange({ transcription })} options={[
          { value: "local", label: "På denne maskinen", hint: "Ingen API-kostnad. Krever lokal modell." },
          { value: "provider", label: <>Ekstern KI-tjeneste <CostBadge /></>,
            hint: "Sender lyden til leverandøren du velger." },
          { value: "off", label: "Bare eksisterende undertekster", hint: "Hopper over lyd som mangler tekst." },
        ]} />
      {value.transcription === "local" && !status.local.installed.whisper ? (
        <Alert tone="info">
          Den lokale modellen er ikke installert. Lukk EmneKlar, kjør setup.bat på nytt og svar «j» på spørsmålet om
          lokale modeller, eller velg et annet alternativ.
        </Alert>
      ) : null}
      {value.transcription === "provider" ? (
        <>
          <div className="ek-grid" data-cols="2">
            <SelectField label="Leverandør" value={value.transcription_provider_id}
              onChange={(e) => onChange({ transcription_provider_id: e.target.value, transcription_model: "" })}
              options={status.providers.map((p) => ({ value: p.id, label: p.name }))} />
            {models.length ? (
              <SelectField label="Modell" value={value.transcription_model}
                onChange={(e) => onChange({ transcription_model: e.target.value })} options={[
                  { value: "", label: `Standard (${models.find((m) => m.default)?.label ?? "katalogen"})` },
                  ...models.map((m) => ({ value: m.id, label: m.label })),
                ]} />
            ) : (
              <TextField label="Modell eller deployment" value={value.transcription_model}
                onChange={(e) => onChange({ transcription_model: e.target.value })}
                hint="Navnet hos leverandøren, for eksempel deployment-navnet i Azure." />
            )}
            <SelectField label="Språk i opptakene" value={value.transcription_language}
              onChange={(e) => onChange({ transcription_language: e.target.value })}
              options={languages.map(([code, label]) => ({ value: code, label }))} />
          </div>
          {showPlan && plan && !plan.available ? <Alert tone="warning">{plan.reason}</Alert> : null}
          <Alert tone="info" title="Personvern">
            Opptak kan inneholde studenters stemmer. Bruk bare en leverandør institusjonen har databehandleravtale med.
            Du ser antall minutter og mottaker i estimatet og godkjenner før noe sendes.
          </Alert>
          <Disclosure summary="Les mer om ekstern transkribering">
            <ul className="ek-small">
              <li>Bare lyden sendes, i biter på 60–120 sekunder kuttet ved pauser. Stille biter sendes ikke.</li>
              <li>Teksten fra forrige bit sendes med som stavehjelp. Videotittel og annet innhold fra emnet sendes ikke.</li>
              <li>Ferdige transkripsjoner lagres lokalt, så samme fil sendes aldri to ganger.</li>
              <li>Leverandøren tar betalt per minutt lyd. EmneKlar kjenner ikke prisene.</li>
            </ul>
          </Disclosure>
        </>
      ) : null}
    </div>
  );
}

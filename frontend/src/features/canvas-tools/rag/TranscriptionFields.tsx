// Emne-RAG: choice of transcription service (used under «Tilpass kilder → Avansert» and under «Innstillinger»).
import { Alert, RadioGroup, SelectField, TextField } from "../../../design-system";
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
  return (
    <div className="ek-stack" data-gap="4">
      <RadioGroup legend="Transkripsjon når videoen mangler teksting" name={name} value={value.transcription}
        onChange={(transcription) => onChange({ transcription })} options={[
          { value: "local", label: "Lokalt med NB-Whisper",
            hint: "Ingen kostnad, og lyden forlater ikke maskinen. Best på norsk og dialekter. Krever lokale modeller " +
              "(setup-emne-rag.bat) og tar tid på maskiner uten GPU." },
          { value: "provider", label: "KI-leverandør (OpenAI, Azure OpenAI eller egen server)",
            hint: "Ekstra kostnad: leverandøren tar betalt per minutt lyd. Raskt og uten store installasjoner. Bare " +
              "lyden sendes, i biter på 60–120 sekunder, og bare etter at du har godtatt det i estimatet." },
          { value: "off", label: "Ikke transkriber", hint: "Bare eksisterende teksting brukes. Ingen kostnad." },
        ]} />
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
                hint="Navnet på transkripsjonsmodellen hos leverandøren, for eksempel deployment-navnet i Azure." />
            )}
            <TextField label="Språk (valgfritt)" value={value.transcription_language} maxLength={3}
              onChange={(e) => onChange({ transcription_language: e.target.value.trim().toLowerCase() })}
              hint="Tom = gjenkjennes automatisk. «no» for norsk, «en» for engelsk." />
          </div>
          {showPlan && plan && !plan.available ? <Alert tone="warning">{plan.reason}</Alert> : null}
          <Alert tone="info" title="Personvern">
            Opptak kan inneholde stemmene til studenter. Sjekk at institusjonen har databehandleravtale med
            leverandøren før du bruker ekstern transkripsjon. Du ser antall minutter og hvem det sendes til i
            estimatet, og ingenting sendes uten at du godkjenner det.
          </Alert>
        </>
      ) : null}
    </div>
  );
}

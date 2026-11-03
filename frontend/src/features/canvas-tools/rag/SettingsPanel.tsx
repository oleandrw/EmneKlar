// Emne-RAG → Innstillinger: search model, reranking, speech-to-text, limits and the local model status.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useState } from "react";

import { api } from "../../../core/api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  RadioGroup,
  SelectField,
  Switch,
  TextField,
  useToast,
  type Column,
} from "../../../design-system";
import { formatMb, type LocalModel, type RagSettings, type RagStatus } from "./api";

const KIND_LABEL: Record<LocalModel["kind"], string> = { embedding: "Embedding", reranker: "Rerangering",
  whisper: "Tale til tekst (norsk)", whisper_other: "Tale til tekst (annet språk)" };

export function SettingsPanel({ status, courseId }: { status: RagStatus; courseId: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<RagSettings>(status.settings);
  const set = (patch: Partial<RagSettings>) => setForm((f) => ({ ...f, ...patch }));
  const save = useMutation({
    mutationFn: () => api.patch(`/api/settings/rag`, form),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["rag", courseId] });
      toast.show({ tone: "success", title: "Innstillingene er lagret" });
    },
  });
  const models = status.local.models;
  const options = (kind: LocalModel["kind"]) => [
    { value: "", label: `Standard (${models.find((m) => m.kind === kind && m.default)?.label ?? "katalogen"})` },
    ...models.filter((m) => m.kind === kind).map((m) => ({ value: m.id, label: `${m.label} – ca. ${formatMb(m.size_mb)}` })),
  ];
  const installed = status.local.installed;
  const providerType = status.providers.find((p) => p.id === form.transcription_provider_id)?.type ?? "";
  const transcriptionModels = status.transcription_models.filter((m) => m.provider_type === providerType);
  const columns: Column<LocalModel>[] = [
    { key: "label", header: "Modell", rowHeader: true, cell: (m) => (
      <span className="ek-stack" data-gap="1"><span>{m.label}</span><span className="ek-xs ek-muted">{m.id}</span></span>
    ) },
    { key: "kind", header: "Bruk", cell: (m) => KIND_LABEL[m.kind] },
    { key: "size", header: "Størrelse", numeric: true, cell: (m) => `ca. ${formatMb(m.size_mb)}` },
    { key: "state", header: "Status", cell: (m) => m.downloaded ? <Badge tone="success">Lastet ned</Badge> : <Badge>Ikke lastet ned</Badge> },
  ];
  return (
    <div className="ek-stack" data-gap="6">
      <Card title="Søk" headingLevel={2}>
        <div className="ek-stack" data-gap="6">
          <RadioGroup legend="Embedding (semantisk søk)" name="rag-embedding" value={form.embedding_backend}
            onChange={(embedding_backend) => set({ embedding_backend })} options={[
              { value: "local", label: "Lokal modell på denne maskinen", hint: "Anbefalt. Ingenting forlater maskinen." },
              { value: "provider", label: "KI-leverandør (OpenAI-kompatibel)",
                hint: "For eksempel Ollama med bge-m3 lokalt, eller OpenAI/Azure. Ekstern leverandør krever samtykke." },
              { value: "none", label: "Bare nøkkelordsøk (BM25)", hint: "Raskest og uten modeller, men finner færre treff." },
            ]} />
          {form.embedding_backend === "local" ? (
            <SelectField label="Embedding-modell" value={form.embedding_model} options={options("embedding")}
              onChange={(e) => set({ embedding_model: e.target.value })}
              hint="Bytter du modell, må indeksen bygges på nytt." />
          ) : null}
          {form.embedding_backend === "provider" ? (
            <div className="ek-grid" data-cols="2">
              <SelectField label="Leverandør" value={form.embedding_provider_id}
                onChange={(e) => set({ embedding_provider_id: e.target.value })}
                options={status.providers.map((p) => ({ value: p.id, label: p.name }))} />
              <TextField label="Modell hos leverandøren" value={form.embedding_provider_model}
                onChange={(e) => set({ embedding_provider_model: e.target.value })} hint="For eksempel bge-m3 i Ollama." />
            </div>
          ) : null}
          <Switch label="Rerangering med lokal modell" checked={form.reranker_enabled}
            onChange={(reranker_enabled) => set({ reranker_enabled })} />
          {form.reranker_enabled ? (
            <SelectField label="Rerangeringsmodell" value={form.reranker_model} options={options("reranker")}
              onChange={(e) => set({ reranker_model: e.target.value })} />
          ) : null}
          <div className="ek-grid" data-cols="2">
            <TextField label="Kandidater fra søket" type="number" min={10} max={100} value={form.candidates}
              onChange={(e) => set({ candidates: Number(e.target.value) })} hint="30–50 anbefales." />
            <TextField label="Utdrag til svaret" type="number" min={3} max={10} value={form.top_k}
              onChange={(e) => set({ top_k: Number(e.target.value) })} hint="5–8 anbefales." />
          </div>
          <Switch label="Skriv om vage spørsmål med KI før søket" checked={form.query_rewrite}
            onChange={(query_rewrite) => set({ query_rewrite })} />
          <p className="ek-xs ek-muted">Korte og presise spørsmål søkes alltid slik de er skrevet.</p>
        </div>
      </Card>

      <Card title="Video, lyd og filer" headingLevel={2}>
        <div className="ek-stack" data-gap="4">
          <RadioGroup legend="Transkripsjon når videoen mangler teksting" name="rag-transcription" value={form.transcription}
            onChange={(transcription) => set({ transcription })} options={[
              { value: "local", label: "Lokalt med NB-Whisper", hint: "Best på norsk og dialekter. Krever lokale modeller (setup-emne-rag.bat)." },
              { value: "provider", label: "KI-leverandør (OpenAI, Azure OpenAI eller egen server)",
                hint: "Ingen store installasjoner. Bare lyden sendes, i biter på 60–120 sekunder, etter at du har godkjent det. Teksten fra forrige bit sendes med som stavehjelp." },
              { value: "off", label: "Ikke transkriber", hint: "Bare eksisterende teksting brukes." },
            ]} />
          {form.transcription === "provider" ? (
            <>
              <div className="ek-grid" data-cols="2">
                <SelectField label="Leverandør" value={form.transcription_provider_id}
                  onChange={(e) => set({ transcription_provider_id: e.target.value, transcription_model: "" })}
                  options={status.providers.map((p) => ({ value: p.id, label: p.name }))} />
                {transcriptionModels.length ? (
                  <SelectField label="Modell" value={form.transcription_model}
                    onChange={(e) => set({ transcription_model: e.target.value })} options={[
                      { value: "", label: `Standard (${transcriptionModels.find((m) => m.default)?.label ?? "katalogen"})` },
                      ...transcriptionModels.map((m) => ({ value: m.id, label: m.label })),
                    ]} />
                ) : (
                  <TextField label="Modell eller deployment" value={form.transcription_model}
                    onChange={(e) => set({ transcription_model: e.target.value })}
                    hint="Navnet på transkripsjonsmodellen hos leverandøren, for eksempel deployment-navnet i Azure." />
                )}
                <TextField label="Språk (valgfritt)" value={form.transcription_language} maxLength={3}
                  onChange={(e) => set({ transcription_language: e.target.value.trim().toLowerCase() })}
                  hint="Tom = gjenkjennes automatisk. «no» for norsk, «en» for engelsk." />
              </div>
              {status.transcription.plan && !status.transcription.plan.available ? (
                <Alert tone="warning">{status.transcription.plan.reason}</Alert>
              ) : null}
              <Alert tone="info" title="Personvern">
                Opptak kan inneholde stemmene til studenter. Sjekk at institusjonen har databehandleravtale med
                leverandøren før du bruker ekstern transkripsjon. Du ser antall minutter og hvem det sendes til i
                estimatet, og ingenting sendes uten at du godkjenner det.
              </Alert>
            </>
          ) : null}
          <div className="ek-grid" data-cols="2">
            <SelectField label="NB-Whisper-modell" value={form.whisper_model}
              onChange={(e) => set({ whisper_model: e.target.value as RagSettings["whisper_model"] })}
              hint="Automatisk: large på GPU, small eller medium på CPU." options={[
                { value: "auto", label: "Automatisk" }, { value: "tiny", label: "Tiny (raskest)" },
                { value: "base", label: "Base" }, { value: "small", label: "Small" }, { value: "medium", label: "Medium" },
                { value: "large", label: "Large (best, tregest)" },
              ]} />
            <SelectField label="Modell for annet språk enn norsk" value={form.whisper_other_language_model}
              options={options("whisper_other")} onChange={(e) => set({ whisper_other_language_model: e.target.value })} />
            <SelectField label="Maskinvare" value={form.device}
              onChange={(e) => set({ device: e.target.value as RagSettings["device"] })} options={[
                { value: "auto", label: "Automatisk (GPU hvis tilgjengelig)" }, { value: "cpu", label: "Bare CPU" },
                { value: "cuda", label: "NVIDIA-GPU (CUDA)" },
              ]} />
            <TextField label="Største fil (MB)" type="number" min={1} max={500} value={form.max_file_mb}
              onChange={(e) => set({ max_file_mb: Number(e.target.value) })} />
            <TextField label="Største video (MB)" type="number" min={10} max={20000} value={form.max_video_mb}
              onChange={(e) => set({ max_video_mb: Number(e.target.value) })} />
          </div>
          <Switch label="Hent teksting fra YouTube" checked={form.youtube_captions}
            onChange={(youtube_captions) => set({ youtube_captions })} />
          <p className="ek-xs ek-muted">
            YouTube-teksting hentes med et uoffisielt grensesnitt. Lyd fra YouTube lastes aldri ned; videoer uten teksting
            hoppes over.
          </p>
        </div>
      </Card>

      <div className="ek-cluster">
        <Button variant="primary" icon={<Save aria-hidden="true" />} onClick={() => save.mutate()} loading={save.isPending}>
          Lagre innstillinger
        </Button>
      </div>
      {save.error ? <Alert tone="danger" role="alert">{(save.error as Error).message}</Alert> : null}

      <Card title="Lokale modeller" headingLevel={2}>
        <div className="ek-stack" data-gap="4">
          {installed.embedding || installed.whisper ? (
            <p className="ek-small">
              Maskinvare: {status.local.device === "cuda" ? "NVIDIA-GPU (CUDA)" : "CPU"}. Modellene lagres i{" "}
              <span className="ek-break">{status.local.models_dir}</span>. De lastes ned første gang de brukes, og du
              ser størrelsen før det skjer.
            </p>
          ) : (
            <Alert tone="info" title="Lokale modeller er ikke installert">
              Uten dem bruker Emne-RAG nøkkelordsøk og eksisterende teksting. Lukk EmneKlar og dobbeltklikk{" "}
              <strong>setup-emne-rag.bat</strong> i EmneKlar-mappen (eller kjør <code>setup.bat --rag</code>). Det laster ned
              flere GB. <code>update.bat</code> beholder dem senere.
            </Alert>
          )}
          <DataTable caption="Lokale modeller" captionHidden columns={columns} rows={models} rowKey={(m) => m.id} />
        </div>
      </Card>
    </div>
  );
}

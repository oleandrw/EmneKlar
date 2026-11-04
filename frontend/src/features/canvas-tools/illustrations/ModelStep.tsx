// Step 2 – Velg KI-modeller: quality profile (default «Maksimal kvalitet») and, for advanced users, models per role.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Gauge, Rocket, Scale } from "lucide-react";
import type { ReactElement } from "react";
import { Link } from "react-router";

import { api } from "../../../core/api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Disclosure,
  KeyValue,
  RadioGroup,
  SelectField,
  TextField,
  useToast,
} from "../../../design-system";
import type { Amount, Catalog, Choices, IllustrationSettings, QualityProfileId, Status } from "./api";

const PROFILE_ICON: Record<QualityProfileId, ReactElement> = { max: <Gauge />, balanced: <Scale />, fast: <Rocket /> };
const ROLE_FIELD: Record<string, keyof IllustrationSettings> = {
  illustration_analysis: "analysis_model",
  illustration_planning: "planning_model",
  illustration_review: "review_model",
};

export function ModelStep({ settings, onChange, status, catalog }: {
  settings: IllustrationSettings;
  onChange: (settings: IllustrationSettings) => void;
  status: Status;
  catalog: Catalog;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const set = (patch: Partial<IllustrationSettings>) => onChange({ ...settings, ...patch });
  const save = useMutation({
    mutationFn: () => api.put<{ settings: IllustrationSettings; choices: Choices }>("/api/illustrations/settings", settings),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["illustrations"] });
      toast.show({ tone: "success", title: "Lagret som standard for KI-bildeassistenten" });
    },
  });
  const choices = status.choices;
  const provider = status.image_providers.find((p) => p.id === settings.image_provider_id);
  const imageModels = provider?.models ?? [];
  const textOptions = (vision: boolean) => [
    { value: "", label: "Kvalitetsprofilen velger" },
    ...status.text_models.filter((m) => !vision || m.vision).map((m) => ({ value: m.ref, label: `${m.display_name} (${m.provider_id})` })),
  ];

  return (
    <Card title="2. Velg KI-modeller" description="Ulike modeller brukes til det de er best på: analyse og bildeplan, bildegenerering og kvalitetskontroll."
      actions={<Button size="sm" onClick={() => save.mutate()} loading={save.isPending}>Lagre som standard</Button>}>
      <div className="ek-stack" data-gap="6">
        {!status.ai.available ? (
          <Alert tone="info" title="KI er ikke klar">
            {status.ai.reason} <Link to="/innstillinger/ki-assistenter">Sett opp KI-assistenter</Link>
          </Alert>
        ) : null}
        <RadioGroup<QualityProfileId>
          legend="Kvalitetsprofil"
          name="illustration-profile"
          variant="card"
          columns={3}
          value={settings.quality_profile}
          onChange={(quality_profile) => set({ quality_profile })}
          options={catalog.quality_profiles.map((p) => ({
            value: p.id,
            label: p.default ? `${p.label} (standard)` : p.label,
            hint: p.description,
            icon: PROFILE_ICON[p.id],
          }))}
        />
        <RadioGroup<Amount>
          legend="Mengde illustrasjoner"
          name="illustration-amount"
          columns={3}
          value={settings.amount}
          onChange={(amount) => set({ amount })}
          hint="Antallet styres av faglig behov – sider uten naturlig behov får ingen bilder."
          options={[
            { value: "low", label: "Lav", hint: "Bare der et bilde tydelig hjelper." },
            { value: "balanced", label: "Balansert (standard)", hint: "Vanligvis null til to per side." },
            { value: "high", label: "Høy", hint: "Inntil fire per side, aldri uten faglig funksjon." },
          ]}
        />
        <div className="ek-stack" data-gap="2">
          <h3>Modeller som brukes nå</h3>
          <KeyValue items={[
            ...["illustration_analysis", "illustration_planning", "illustration_review"].map((role) => {
              const choice = choices.roles[role];
              return [choice?.label ?? role, choice?.primary
                ? <span key={role}>{choice.primary.display_name} <span className="ek-small ek-muted">– {choice.reason}</span></span>
                : <Badge key={role} tone="warning">Ingen modell tilgjengelig</Badge>] as [string, ReactElement];
            }),
            ["Bildegenerering", choices.image.model
              ? <span>{choices.image.model.label}, kvalitet {choices.image.quality} <span className="ek-small ek-muted">– {choices.image.reason}</span></span>
              : <Badge tone="warning">{choices.image.unavailable_reason ?? "Ingen bildemodell"}</Badge>],
          ]} />
          {!choices.image.available && choices.image.unavailable_reason ? (
            <Alert tone="warning">{choices.image.unavailable_reason}</Alert>
          ) : null}
          <p className="ek-small ek-muted">
            Claude-modellene brukes til analyse, bildeplan og kvalitetskontroll. Anthropic har ikke noen bildegenerering – bildene lages av OpenAIs bildemodeller
            (eller en annen OpenAI-kompatibel tjeneste du setter opp).
          </p>
        </div>
        <Disclosure summary="Avanserte modellvalg og kostnader">
          <div className="ek-stack" data-gap="4">
            <div className="ek-grid" data-cols="3" data-gap="4">
              {Object.entries(ROLE_FIELD).map(([role, field]) => (
                <SelectField key={role} label={catalog.roles[role] ?? role} value={String(settings[field] ?? "")}
                  onChange={(e) => set({ [field]: e.target.value } as Partial<IllustrationSettings>)}
                  options={textOptions(role === "illustration_review")} />
              ))}
            </div>
            <div className="ek-grid" data-cols="3" data-gap="4">
              <SelectField label="Leverandør for bilder" value={settings.image_provider_id}
                onChange={(e) => set({ image_provider_id: e.target.value, image_model: "" })}
                options={status.image_providers.map((p) => ({ value: p.id, label: `${p.name}${p.configured ? "" : " (ikke satt opp)"}` }))} />
              {provider?.needs_model_name ? (
                <TextField label="Bildemodell / deployment" value={settings.image_model}
                  onChange={(e) => set({ image_model: e.target.value })} hint="Navnet hos leverandøren." />
              ) : (
                <SelectField label="Bildemodell" value={settings.image_model} onChange={(e) => set({ image_model: e.target.value })}
                  options={[{ value: "", label: "Kvalitetsprofilen velger" }, ...imageModels.map((m) => ({ value: m.id, label: `${m.label} – ${m.description}` }))]} />
              )}
              <SelectField label="Bildekvalitet" value={settings.image_quality}
                onChange={(e) => set({ image_quality: e.target.value as IllustrationSettings["image_quality"] })}
                options={[{ value: "", label: "Kvalitetsprofilen velger" }, ...["low", "medium", "high", "xhigh", "max"].map((q) => ({ value: q, label: q }))]} />
              <SelectField label="Bildeformat" value={settings.image_size}
                onChange={(e) => set({ image_size: e.target.value as IllustrationSettings["image_size"] })}
                options={[{ value: "1536x1024", label: "Liggende 3:2 (1536 × 1024)" }, { value: "1024x1024", label: "Kvadratisk (1024 × 1024)" },
                  { value: "1024x1536", label: "Stående 2:3 (1024 × 1536)" }]} />
              <TextField label="Kostnadsgrense per jobb (USD)" type="number" min={0} step="0.5" inputMode="decimal"
                value={settings.cost_limit_usd ?? ""} optional
                hint="Jobben stopper før et kall som ville passert grensen. Det som er laget, beholdes."
                onChange={(e) => set({ cost_limit_usd: e.target.value === "" ? null : Number(e.target.value) })} />
              <TextField label="Mappe i Canvas-filer" value={settings.folder} onChange={(e) => set({ folder: e.target.value })} />
            </div>
            <Checkbox label="Bruk godkjente bilder som stilreferanse" hint="Når bildemodellen støtter referansebilder, sendes inntil noen få godkjente bilder fra emnet med, slik at nye bilder får samme uttrykk."
              checked={settings.use_reference_images} onChange={(e) => set({ use_reference_images: e.target.checked })} />
            <Checkbox label="Lag bildetekst under bildene" checked={settings.captions} onChange={(e) => set({ captions: e.target.checked })} />
          </div>
        </Disclosure>
      </div>
    </Card>
  );
}

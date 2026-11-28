// Step 2 – Bildeinnstillinger: quality, number of images and design profile. The system picks the best available
// models for the quality profile; model names, image formats, widths and costs live under «Avanserte innstillinger».
// Every model selector here reads the model registry (core/models.ts), and the image settings shown are the ones the
// chosen image model supports.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Gauge, Rocket, Scale } from "lucide-react";
import type { ReactElement } from "react";
import { Link } from "react-router";

import { api } from "../../../core/api/client";
import { modelOptions, selectableModels, useModelRegistry } from "../../../core/models";
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
import type { Amount, Catalog, IllustrationSettings, ImageFormat, QualityProfileId, Status } from "./api";
import { DesignSettings } from "./DesignSettings";

const PROFILE_ICON: Record<QualityProfileId, ReactElement> = { max: <Gauge />, balanced: <Scale />, fast: <Rocket /> };
const ROLE_FIELD: Record<string, keyof IllustrationSettings> = {
  illustration_analysis: "analysis_model",
  illustration_planning: "planning_model",
  illustration_review: "review_model",
};

export function ImageSettingsStep({ courseId, settings, onChange, status, catalog }: {
  courseId: string;
  settings: IllustrationSettings;
  onChange: (settings: IllustrationSettings) => void;
  status: Status;
  catalog: Catalog;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const set = (patch: Partial<IllustrationSettings>) => onChange({ ...settings, ...patch });
  const save = useMutation({
    mutationFn: () => api.put("/api/illustrations/settings", settings),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["illustrations"] });
      toast.show({ tone: "success", title: "Innstillingene er lagret som standard" });
    },
  });
  const choices = status.choices;
  const registry = useModelRegistry();
  const models = registry.data?.models;
  const provider = status.image_providers.find((p) => p.id === settings.image_provider_id);
  const AUTO = { value: "", label: "Velges automatisk ut fra kvalitet" };
  const textOptions = (role: string, current: string) => [
    AUTO,
    ...modelOptions(models, { requires: catalog.role_requires?.[role] ?? ["text"] }, { value: "ref", current }),
  ];
  const imageNeed = { requires: ["image_generation"], providerId: settings.image_provider_id };
  const imageModels = selectableModels(models, imageNeed);
  // The image model whose parameters decide which settings are shown: the one chosen here, else the automatic choice.
  const chosenImage = imageModels.find((m) => m.model_id === settings.image_model);
  const automatic = !settings.image_model && choices.image.provider_id === settings.image_provider_id ? choices.image.model : null;
  const imageParams = chosenImage?.params ?? automatic ?? null;
  const qualities = imageParams?.qualities ?? registry.data?.image_qualities ?? ["low", "medium", "high"];
  const complexities = imageParams?.complexities ?? [];
  const takesReferences = imageParams ? Boolean(imageParams.reference_images) : true;
  const exactFormat = settings.image_format === "auto" || !imageParams || Boolean(imageParams.aspect_sizes?.[settings.image_format])
    || ["3:2", "1:1", "2:3"].includes(settings.image_format);
  const notes = [choices.image.note, ...Object.values(choices.roles).map((r) => (r.note ? `${r.label}: ${r.note}` : null))]
    .filter((n): n is string => Boolean(n));
  const missing = ["illustration_analysis", "illustration_planning", "illustration_review"].some((r) => !choices.roles[r]?.primary)
    || !choices.image.available;

  return (
    <Card title="2. Bildeinnstillinger" description="Velg kvalitet, antall bilder og designprofil. EmneKlar velger selv de beste tilgjengelige KI-modellene for kvaliteten du velger.">
      <div className="ek-stack" data-gap="6">
        {!status.ai.available ? (
          <Alert tone="info" title="KI er ikke klar">
            {status.ai.reason} <Link to="/innstillinger/ki-assistenter">Sett opp KI-assistenter</Link>
          </Alert>
        ) : missing ? (
          <Alert tone="warning">Noen KI-oppgaver mangler en tilgjengelig modell. Se «Avanserte innstillinger» nederst.</Alert>
        ) : null}
        {notes.length ? (
          <Alert tone="warning" title="Et modellvalg er ikke lenger tilgjengelig">
            {notes.map((n) => <p key={n}>{n}</p>)}
            <p>Velg en annen modell under «Avanserte innstillinger», eller slå modellen på igjen under{" "}
              <Link to="/innstillinger/ki-assistenter">Innstillinger → KI-assistenter</Link>.</p>
          </Alert>
        ) : null}
        <RadioGroup<QualityProfileId>
          legend="Kvalitet"
          name="illustration-profile"
          variant="card"
          columns={3}
          value={settings.quality_profile}
          onChange={(quality_profile) => set({ quality_profile })}
          options={catalog.quality_profiles.map((p) => ({
            value: p.id,
            label: p.default ? `${p.label} (standard)` : p.label,
            hint: p.id === "max" ? "Grundigst analyse og beste bildekvalitet." : p.id === "balanced" ? "God kvalitet, kortere tid og lavere kostnad." : "Raskest og rimeligst, færre kontrollrunder.",
            icon: PROFILE_ICON[p.id],
          }))}
        />
        <RadioGroup<Amount>
          legend="Antall illustrasjoner"
          name="illustration-amount"
          columns={3}
          value={settings.amount}
          onChange={(amount) => set({ amount })}
          hint="KI foreslår bare bilder der de gir faglig verdi – sider uten naturlig behov får ingen."
          options={[
            { value: "low", label: "Lav", hint: "Bare der et bilde tydelig hjelper." },
            { value: "balanced", label: "Balansert (standard)", hint: "Vanligvis null til to per side." },
            { value: "high", label: "Høy", hint: "Flere bilder, men aldri uten faglig funksjon." },
          ]}
        />
        <DesignSettings courseId={courseId} status={status} catalog={catalog} />
        <div className="ek-stack" data-gap="2">
          <h3>Tekst ved bildene</h3>
          <Checkbox label="Korte etiketter i diagrammer, modeller og prosesser" hint="Bildene forklarer mest mulig visuelt. Tekst brukes bare der den gjør innholdet lettere å forstå, som korte begreper på innholdets språk – og kontrolleres for skrivefeil."
            checked={settings.text_in_images === "auto"} onChange={(e) => set({ text_in_images: e.target.checked ? "auto" : "never" })} />
          <Checkbox label="Vis bildetekst under bildet når den tilfører noe" hint="Du kan slå bildeteksten av eller på for hvert bilde."
            checked={settings.captions} onChange={(e) => set({ captions: e.target.checked })} />
          <Checkbox label={`Merk bildene med «${settings.credit_text || "KI-generert illustrasjon"}»`} hint="Vises som en egen linje under bildet, adskilt fra bildeteksten."
            checked={settings.credit} onChange={(e) => set({ credit: e.target.checked })} />
        </div>
        <Disclosure summary="Avanserte innstillinger">
          <div className="ek-stack" data-gap="5">
            <div className="ek-stack" data-gap="2">
              <h3>KI-modeller i bruk</h3>
              <KeyValue items={[
                ...["illustration_analysis", "illustration_planning", "illustration_review"].map((role) => {
                  const choice = choices.roles[role];
                  return [choice?.label ?? role, choice?.primary
                    ? <span key={role}>{choice.primary.display_name} <span className="ek-small ek-muted">– {choice.reason}</span></span>
                    : <Badge key={role} tone="warning">Ingen modell tilgjengelig</Badge>] as [string, ReactElement];
                }),
                ["Bildegenerering", choices.image.model
                  ? <span>{choices.image.model.label}, kvalitet {choices.image.quality}{choices.image.complexity ? `, kompleksitet ${choices.image.complexity}` : ""} <span className="ek-small ek-muted">– {choices.image.reason}</span></span>
                  : <Badge tone="warning">{choices.image.unavailable_reason ?? "Ingen bildemodell"}</Badge>],
              ]} />
              <p className="ek-small ek-muted">Modellene her er de som er aktivert under <Link to="/innstillinger/ki-assistenter">Innstillinger → KI-assistenter</Link>. Bilder kan lages av OpenAIs bildemodeller eller en annen OpenAI-kompatibel tjeneste du setter opp.</p>
            </div>
            <div className="ek-grid" data-cols="3" data-gap="4">
              {Object.entries(ROLE_FIELD).map(([role, field]) => (
                <SelectField key={role} label={catalog.roles[role] ?? role} value={String(settings[field] ?? "")}
                  onChange={(e) => set({ [field]: e.target.value } as Partial<IllustrationSettings>)}
                  options={textOptions(role, String(settings[field] ?? ""))} />
              ))}
              <SelectField label="Leverandør for bilder" value={settings.image_provider_id}
                onChange={(e) => set({ image_provider_id: e.target.value, image_model: "" })}
                options={status.image_providers.map((p) => ({ value: p.id, label: `${p.name}${p.configured ? "" : " (ikke satt opp)"}` }))} />
              {provider?.needs_model_name && !imageModels.length ? (
                <TextField label="Bildemodell / deployment" value={settings.image_model} onChange={(e) => set({ image_model: e.target.value })}
                  hint="Navnet hos leverandøren. Du kan også legge modellen til under Innstillinger → KI-assistenter." />
              ) : (
                <SelectField label="Bildemodell" value={settings.image_model} onChange={(e) => set({ image_model: e.target.value })}
                  hint={imageModels.length ? undefined : "Ingen bildemodell er aktivert for leverandøren."}
                  options={[AUTO, ...modelOptions(models, imageNeed, { value: "model_id", current: settings.image_model, describe: true })]} />
              )}
              <SelectField label="Bildekvalitet" value={settings.image_quality}
                onChange={(e) => set({ image_quality: e.target.value as IllustrationSettings["image_quality"] })}
                options={[{ value: "", label: "Velges automatisk" }, ...qualities.map((q) => ({ value: q, label: q })),
                  ...(settings.image_quality && !qualities.includes(settings.image_quality)
                    ? [{ value: settings.image_quality, label: `${settings.image_quality} (støttes ikke av modellen)` }] : [])]} />
              {complexities.length ? (
                <SelectField label="Kompleksitet" value={settings.image_complexity ?? ""} hint="Hvor mye modellen arbeider med bildet."
                  onChange={(e) => set({ image_complexity: e.target.value as IllustrationSettings["image_complexity"] })}
                  options={[{ value: "", label: "Modellens standard" }, ...complexities.map((c) => ({ value: c, label: c }))]} />
              ) : null}
              <SelectField label="Bildeformat" value={settings.image_format}
                hint={exactFormat ? "«Automatisk» velger format per bilde." : "Modellen har ikke dette formatet: bildet lages i nærmeste standardstørrelse (3:2)."}
                onChange={(e) => set({ image_format: e.target.value as ImageFormat })}
                options={Object.entries(catalog.formats).map(([value, label]) => ({ value, label }))} />
              <TextField label="Maksimal visningsbredde i Canvas (px)" type="number" min={240} max={2000} step={10} value={settings.max_width_px}
                hint="Standard 900 px. Bildet krymper på mobil og nettbrett." onChange={(e) => set({ max_width_px: Number(e.target.value) || 900 })} />
              <TextField label="Kostnadsgrense per jobb (USD)" type="number" min={0} step="0.5" inputMode="decimal" optional
                value={settings.cost_limit_usd ?? ""} hint="Jobben stopper før et kall som ville passert grensen."
                onChange={(e) => set({ cost_limit_usd: e.target.value === "" ? null : Number(e.target.value) })} />
              <TextField label="Kreditering" value={settings.credit_text} onChange={(e) => set({ credit_text: e.target.value })} />
              <TextField label="Mappe i Canvas-filer" value={settings.folder} onChange={(e) => set({ folder: e.target.value })} />
            </div>
            {takesReferences ? (
              <Checkbox label="Bruk godkjente bilder som stilreferanse" checked={settings.use_reference_images}
                onChange={(e) => set({ use_reference_images: e.target.checked })} />
            ) : null}
            <div>
              <Button size="sm" onClick={() => save.mutate()} loading={save.isPending}>Lagre som standard</Button>
            </div>
          </div>
        </Disclosure>
      </div>
    </Card>
  );
}

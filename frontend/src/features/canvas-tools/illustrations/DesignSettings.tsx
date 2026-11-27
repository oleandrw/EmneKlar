// The course's design profile inside «Bildeinnstillinger»: a ready-made profile, or «Egendefinert» with one text box
// for a whole prompt. A profile is one prompt that is used in every image of the course.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Save, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

import { AiBadge, AiConsent, type AiPlan } from "../../../core/ai";
import { api } from "../../../core/api/client";
import { formatDateTime } from "../../../core/format";
import {
  Alert,
  Badge,
  Button,
  Disclosure,
  IconButton,
  ImageFrame,
  RadioGroup,
  SelectField,
  TextArea,
  TextField,
  useToast,
} from "../../../design-system";
import type { Catalog, DesignData, DesignProfile, ImageFormat, Status } from "./api";

const CUSTOM = "custom";
const MAX_PROMPT = 8000;

export function DesignSettings({ courseId, status, catalog }: { courseId: string; status: Status; catalog: Catalog }) {
  const client = useQueryClient();
  const toast = useToast();
  const active = status.design;
  const [draft, setDraft] = useState<DesignData | null>(active?.data ?? null);
  const [origin, setOrigin] = useState<"preset" | "ai" | "custom">("custom");
  const [plan, setPlan] = useState<AiPlan | null>(null);
  const [samplePlan, setSamplePlan] = useState<(AiPlan & { estimated_cost_usd: number | null }) | null>(null);
  const [sample, setSample] = useState<{ url: string; id: string } | null>(null);
  useEffect(() => setDraft(active?.data ?? null), [active?.id, active?.data]);

  const refresh = () => client.invalidateQueries({ queryKey: ["illustrations", courseId] });
  const fromStyle = useMutation({
    mutationFn: (style_key: string) => api.post<{ data: DesignData }>(`/api/courses/${courseId}/illustrations/design/from-style`, { style_key }),
    onSuccess: (r) => {
      setDraft(r.data);
      setOrigin("preset");
    },
  });
  const prepare = useMutation({
    mutationFn: () => api.post<AiPlan>(`/api/courses/${courseId}/illustrations/design/suggest/prepare`),
    onSuccess: setPlan,
  });
  const suggest = useMutation({
    mutationFn: () => api.post<{ data: DesignData }>(`/api/courses/${courseId}/illustrations/design/suggest`, { confirmed: true }),
    onSuccess: (r) => {
      setDraft(r.data);
      setOrigin("ai");
      setPlan(null);
    },
  });
  const save = useMutation({
    mutationFn: () => api.put<DesignProfile>(`/api/courses/${courseId}/illustrations/design`, { data: draft, origin }),
    onSuccess: async (p) => {
      await refresh();
      toast.show({ tone: "success", title: `Designprofilen er lagret (versjon ${p.version})` });
    },
  });
  const references = useMutation({
    mutationFn: (ids: string[]) => api.put<DesignProfile>(`/api/courses/${courseId}/illustrations/design/references`, { asset_ids: ids }),
    onSuccess: refresh,
  });
  const prepareSample = useMutation({
    mutationFn: () => api.post<AiPlan & { estimated_cost_usd: number | null }>(`/api/courses/${courseId}/illustrations/design/sample/prepare`),
    onSuccess: setSamplePlan,
  });
  const makeSample = useMutation({
    mutationFn: () => api.post<{ asset: { id: string; url: string } }>(`/api/courses/${courseId}/illustrations/design/sample`, { confirmed: true }),
    onSuccess: (r) => {
      setSample({ url: r.asset.url, id: r.asset.id });
      setSamplePlan(null);
    },
  });
  const candidates = useQuery({
    queryKey: ["illustrations", courseId, "assets"],
    queryFn: () => api.get<{ items: { asset_id: string; thumb_url: string; page_title: string }[] }>(`/api/courses/${courseId}/illustrations/assets`),
  });

  const set = (patch: Partial<DesignData>) => {
    if (draft) setDraft({ ...draft, ...patch });
    setOrigin("custom");
  };
  const refs = active?.reference_assets ?? [];
  const changed = draft && active ? JSON.stringify(draft) !== JSON.stringify(active.data) : Boolean(draft);
  const custom = draft?.style_key === CUSTOM;
  const missingPrompt = Boolean(draft) && !draft?.prompt.trim();
  const error = save.error ?? suggest.error ?? fromStyle.error ?? makeSample.error ?? references.error;

  return (
    <div className="ek-stack" data-gap="4">
      <div className="ek-stack" data-gap="1">
        <h3>Designprofil</h3>
        <p className="ek-small ek-muted">
          Alle bildene i emnet lages med samme prompt for stilen – tilpasset innholdet, men aldri like.
          {active ? ` I bruk: ${active.name}, versjon ${active.version}.` : ""}
        </p>
      </div>
      {plan ? <AiConsent plan={plan} onCancel={() => setPlan(null)} onConfirm={() => suggest.mutate()} loading={suggest.isPending} confirmLabel="Foreslå designprofil" /> : null}
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      <RadioGroup<string>
        legend="Stil"
        name="illustration-style"
        variant="card"
        columns={2}
        value={draft?.style_key ?? ""}
        onChange={(key) => fromStyle.mutate(key)}
        options={catalog.styles.map((s) => ({ value: s.key, label: s.label, hint: s.description }))}
      />
      {draft && custom ? (
        <TextArea label="Prompt" rows={14} maxLength={MAX_PROMPT} value={draft.prompt}
          onChange={(e) => set({ prompt: e.target.value })}
          hint="Lim inn hele prompten, for eksempel en du har fått fra ChatGPT. Den brukes i alle bildene i emnet. Skriv {tema} der temaet for hvert bilde skal settes inn. Uten {tema} står temaet foran prompten." />
      ) : null}
      {draft && !custom && draft.prompt ? (
        <Disclosure summary="Vis prompten">
          <pre className="ek-code-block">{draft.prompt}</pre>
        </Disclosure>
      ) : null}
      {draft && (origin === "ai" || draft.rationale) ? (
        <div className="ek-cluster" data-gap="2">
          {origin === "ai" ? <AiBadge /> : null}
          {draft.rationale ? <span className="ek-small ek-muted">{draft.rationale}</span> : null}
        </div>
      ) : null}
      <div className="ek-cluster" data-gap="2">
        <Button icon={<Sparkles aria-hidden="true" />} onClick={() => prepare.mutate()} loading={prepare.isPending} disabled={!status.ai.available}>
          Foreslå prompt ut fra emnet
        </Button>
        <Button variant="primary" icon={<Save aria-hidden="true" />} onClick={() => save.mutate()} loading={save.isPending}
          disabled={!changed || missingPrompt}>
          Lagre designprofilen
        </Button>
        {changed && !missingPrompt ? <Badge tone="warning">Ikke lagret</Badge> : null}
        {missingPrompt ? <span className="ek-small ek-muted">Lim inn en prompt for å lagre.</span> : null}
      </div>
      <Disclosure summary="Flere valg">
        {draft ? (
          <div className="ek-stack" data-gap="4">
            <TextField label="Navn" value={draft.name} onChange={(e) => set({ name: e.target.value })} />
            <SelectField label="Bildeformat for emnet" value={draft.aspect_ratio}
              hint="«Automatisk» lar KI velge format per bilde (for eksempel 16:9 for prosesser og 4:3 for modeller)."
              onChange={(e) => set({ aspect_ratio: e.target.value as ImageFormat })}
              options={Object.entries(catalog.formats).map(([value, label]) => ({ value, label }))} />
            <div className="ek-stack" data-gap="2">
              <h4>Referansebilder</h4>
              <p className="ek-small ek-muted">Godkjente bilder brukes som stilgrunnlag for nye bilder, og nye bilder kontrolleres mot dem. Inntil fire.</p>
              {refs.length === 0 ? <p className="ek-small">Ingen referansebilder ennå. Velg «Bruk som stilreferanse» på et godkjent bilde.</p> : (
                <div className="ek-thumb-grid">
                  {refs.map((id) => (
                    <div key={id} className="ek-stack" data-gap="1">
                      <ImageFrame size="thumb" src={`/api/illustrations/assets/${id}?size=thumb`} alt="Referansebilde for emnets stil" />
                      <IconButton label="Fjern referansebildet" size="sm" onClick={() => references.mutate(refs.filter((r) => r !== id))}>
                        <X aria-hidden="true" />
                      </IconButton>
                    </div>
                  ))}
                </div>
              )}
              {candidates.data && candidates.data.items.some((c) => !refs.includes(c.asset_id)) && refs.length < 4 ? (
                <div className="ek-thumb-grid">
                  {candidates.data.items.filter((c) => !refs.includes(c.asset_id)).map((c) => (
                    <button key={c.asset_id} type="button" className="ek-thumb-button" onClick={() => references.mutate([...refs, c.asset_id])}>
                      <ImageFrame size="thumb" src={c.thumb_url} alt="" />
                      <span className="ek-small">Bruk bildet fra «{c.page_title}»</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <div className="ek-stack" data-gap="2">
              <div>
                <Button icon={<ImagePlus aria-hidden="true" />} onClick={() => prepareSample.mutate()} loading={prepareSample.isPending}
                  disabled={!status.ai.available || !status.choices.image.available}>
                  Lag eksempelbilde
                </Button>
              </div>
              {samplePlan ? (
                <AiConsent plan={{ ...samplePlan, payload_summary: `${samplePlan.payload_summary ?? ""} Anslått kostnad: ${samplePlan.estimated_cost_usd ?? "ukjent"} USD (ikke garantert).` }}
                  onCancel={() => setSamplePlan(null)} onConfirm={() => makeSample.mutate()} loading={makeSample.isPending} confirmLabel="Lag eksempelbilde" />
              ) : null}
              {sample ? (
                <div className="ek-stack" data-gap="2">
                  <ImageFrame src={sample.url} alt="Eksempelbilde i den lagrede designprofilen" caption={<AiBadge />} />
                  <div>
                    <Button size="sm" onClick={() => references.mutate([...refs, sample.id])} disabled={refs.length >= 4 || refs.includes(sample.id)}>
                      Bruk som stilreferanse
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
            {status.design_versions.length > 1 ? (
              <div className="ek-stack" data-gap="1">
                <h4>Tidligere versjoner</h4>
                <ul className="ek-stack" data-gap="1">
                  {status.design_versions.filter((v) => !v.active).map((v) => (
                    <li key={v.id} className="ek-small">Versjon {v.version}: {v.name} ({v.style_label}){v.created_at ? `, ${formatDateTime(v.created_at)}` : ""}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </Disclosure>
    </div>
  );
}

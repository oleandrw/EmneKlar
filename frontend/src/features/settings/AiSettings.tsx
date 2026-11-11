// Innstillinger → KI-assistenter: providers (keys go to the OS credential store), model registry,
// cost/quality-aware routing and the metadata-only usage log.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, PlugZap, Search, ShieldCheck, Trash } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import { formatDateTime, formatNumber } from "../../core/format";
import { useSession } from "../../core/session";
import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  Dialog,
  Disclosure,
  ExternalLink,
  IconButton,
  PasswordField,
  RadioGroup,
  SelectField,
  Spinner,
  Switch,
  TextField,
  useToast,
  type Column,
} from "../../design-system";

interface Provider {
  id: string;
  type: "openai" | "anthropic" | "azure_openai" | "openai_compatible";
  name: string;
  enabled: boolean;
  endpoint: string | null;
  api_version: string | null;
  last_status: "unknown" | "ok" | "error";
  last_message: string | null;
  last_checked_at: string | null;
  key_configured: boolean;
  local: boolean;
  data_leaves_machine: boolean;
  needs_key: boolean;
  /** The provider's own page for API keys (OpenAI, Anthropic). */
  key_page: string | null;
  /** The cached model list is old: fetched again in the background. */
  models_stale: boolean;
}

/** Providers connected with one action, «Koble til» (a key checked before it is stored). */
const KEY_PROVIDERS: Provider["type"][] = ["openai", "anthropic"];

interface Model {
  id: number;
  provider_id: string;
  model_id: string;
  display_name: string;
  vision: boolean;
  structured_output: boolean;
  context_class: number;
  quality_class: number;
  speed_class: number;
  cost_class: number;
  enabled: boolean;
  source: "catalog" | "discovered" | "user";
  capabilities_known: boolean;
  notes: string | null;
}

interface ShortModel {
  provider_id: string;
  model_id: string;
  display_name: string;
}

interface Routing {
  strategy: string;
  strategies: { id: string; label: string }[];
  tasks: {
    key: string;
    label: string;
    description: string;
    vision: boolean;
    decision: { primary: ShortModel | null; fallbacks: ShortModel[]; reason: string; excluded: string[] };
    manual_model: string | null;
    preferred_provider: string | null;
  }[];
}

interface Usage {
  items: {
    id: number;
    created_at: string;
    task_label: string;
    provider_id: string;
    model_id: string;
    reason: string;
    fallback_used: boolean;
    success: boolean;
    error_code: string | null;
    input_tokens: number;
    output_tokens: number;
    summary: string | null;
  }[];
}

const STRATEGY_HINTS: Record<string, string> = {
  auto: "Bruker den rimeligste modellen som er god nok for oppgaven. Anbefalt.",
  low_cost: "Velger alltid det rimeligste alternativet som oppfyller minstekravene.",
  speed: "Velger raske modeller når de er gode nok.",
  quality: "Velger de sterkeste modellene. Kan koste mer.",
  manual: "Du velger modell for hver oppgave selv.",
};
const CLASS = (n: number, max: number) => `${n} av ${max}`;

function useAiRefresh() {
  const client = useQueryClient();
  return () => {
    for (const key of ["ai-providers", "ai-models", "ai-routing", "session"]) void client.invalidateQueries({ queryKey: [key] });
  };
}

/** One status per card: in the header, never repeated in a box below. */
function connectionStatus(provider: Provider): { tone: "success" | "danger" | "neutral"; label: string } {
  if (provider.needs_key && !provider.key_configured) return { tone: "neutral", label: "Ikke tilkoblet" };
  if (provider.last_status === "ok") return { tone: "success", label: "Tilkoblet" };
  if (provider.last_status === "error") return { tone: "danger", label: "Feil" };
  return { tone: "neutral", label: "Ikke kontrollert" };
}

function ProviderBadges({ provider }: { provider: Provider }) {
  const status = connectionStatus(provider);
  return (
    <>
      {provider.local ? <Badge tone="teal">Lokal – data forlater ikke maskinen</Badge> : <Badge>Ekstern tjeneste</Badge>}
      <Badge tone={status.tone}>{status.label}</Badge>
    </>
  );
}

/** The last check failed: what went wrong, said once. */
function ProviderError({ provider }: { provider: Provider }) {
  return provider.last_status === "error" && provider.last_message
    ? <p className="ek-provider-error ek-small">{provider.last_message}</p> : null;
}

function SwitchNote({ provider }: { provider: Provider }) {
  return provider.key_configured && !provider.enabled ? (
    <p className="ek-small ek-muted">Nøkkelen er lagret, men {provider.name} brukes ikke før «Bruk {provider.name}» er slått på.</p>
  ) : null;
}

/** OpenAI and Anthropic: one action, «Koble til», that checks the key with the provider and stores it only when the
 * check succeeds. The model list is fetched with the check (and later in the background); endpoint and a manual check
 * are under «Avansert». */
function KeyProviderCard({ provider }: { provider: Provider }) {
  const refresh = useAiRefresh();
  const [key, setKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [endpoint, setEndpoint] = useState(provider.endpoint ?? "");
  const keyField = useRef<HTMLInputElement>(null);
  const changeButton = useRef<HTMLButtonElement>(null);
  const connect = useMutation({
    mutationFn: (apiKey: string) => api.post<Provider>(`/api/ai/providers/${provider.id}/connect`, { api_key: apiKey }),
    onSuccess: () => {
      setKey("");
      setReplacing(false);
      refresh();
    },
  });
  const check = useMutation({ mutationFn: () => api.post<Provider>(`/api/ai/providers/${provider.id}/connect`, {}), onSettled: refresh });
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.put<Provider>(`/api/ai/providers/${provider.id}`, body),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/api/ai/providers/${provider.id}/key`),
    onSuccess: () => {
      setReplacing(false);
      refresh();
    },
  });
  const showForm = !provider.key_configured || replacing;
  // Focus follows the change: into the key field for «Bytt nøkkel», back to «Bytt nøkkel» after connecting or «Avbryt».
  const focusAfter = useRef<"field" | "change" | null>(null);
  useEffect(() => {
    if (focusAfter.current === "field" && showForm) keyField.current?.focus();
    if (focusAfter.current === "change" && !showForm) changeButton.current?.focus();
    focusAfter.current = null;
  }, [showForm]);
  const submit = () => {
    if (connect.isPending) return; // no double requests
    focusAfter.current = provider.key_configured ? "change" : null;
    connect.mutate(key);
  };

  return (
    <Card title={provider.name} headingLevel={3} actions={<ProviderBadges provider={provider} />}>
      <div className="ek-stack">
        <Switch label={`Bruk ${provider.name}`} checked={provider.enabled} onChange={(enabled) => update.mutate({ enabled })} />
        <SwitchNote provider={provider} />
        {showForm ? (
          <form className="ek-stack" data-gap="3" noValidate onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}>
            <PasswordField ref={keyField} label="API-nøkkel" value={key} revealLabel="Vis API-nøkkelen" concealLabel="Skjul API-nøkkelen"
              onChange={(e) => setKey(e.target.value)} readOnly={connect.isPending}
              hint="EmneKlar kontrollerer nøkkelen hos leverandøren og lagrer den bare i Windows Legitimasjonsbehandling. Den vises aldri igjen." />
            {provider.key_page ? (
              <p className="ek-small">
                <ExternalLink href={provider.key_page}>Finn eller lag en API-nøkkel hos {provider.name}</ExternalLink>
              </p>
            ) : null}
            <div className="ek-cluster">
              <Button type="submit" variant="primary" icon={<PlugZap aria-hidden="true" />} loading={connect.isPending}>
                {connect.isPending ? "Kobler til …" : "Koble til"}
              </Button>
              {replacing ? (
                <Button variant="ghost" disabled={connect.isPending} onClick={() => {
                  focusAfter.current = "change";
                  setKey("");
                  connect.reset();
                  setReplacing(false);
                }}>Avbryt</Button>
              ) : null}
            </div>
            {connect.error ? <Alert tone="danger" role="alert">{connect.error.message}</Alert> : null}
          </form>
        ) : (
          <div className="ek-stack" data-gap="3">
            <p className="ek-provider-key">
              <ShieldCheck aria-hidden="true" size={18} />
              <span><span className="ek-strong">Nøkkel lagret sikkert</span> <span className="ek-muted">i Windows Legitimasjonsbehandling</span></span>
            </p>
            <ProviderError provider={provider} />
            <div className="ek-cluster">
              <Button ref={changeButton} icon={<KeyRound aria-hidden="true" />} onClick={() => {
                focusAfter.current = "field";
                connect.reset();
                setReplacing(true);
              }}>Bytt nøkkel</Button>
              <Button variant="ghost" icon={<Trash aria-hidden="true" />} loading={remove.isPending} onClick={() => remove.mutate()}
                aria-label={`Fjern nøkkelen til ${provider.name}`}>
                Fjern
              </Button>
            </div>
          </div>
        )}
        {remove.error || update.error ? <Alert tone="danger" role="alert">{(remove.error ?? update.error)!.message}</Alert> : null}
        <Disclosure summary="Avansert">
          <div className="ek-stack" data-gap="4">
            {provider.type === "openai" ? (
              <form className="ek-stack" data-gap="2" onSubmit={(e) => {
                e.preventDefault();
                update.mutate({ endpoint });
              }}>
                <TextField label="Endepunkt" type="url" value={endpoint} onChange={(e) => setEndpoint(e.target.value)}
                  hint="Standard er https://api.openai.com/v1. Endre bare hvis du bruker en egen proxy med samme API." />
                <div><Button type="submit" size="sm" loading={update.isPending}>Lagre endepunkt</Button></div>
              </form>
            ) : null}
            <div className="ek-stack" data-gap="1">
              <div>
                <Button size="sm" icon={<PlugZap aria-hidden="true" />} disabled={!provider.key_configured}
                  loading={check.isPending} onClick={() => check.mutate()}>
                  {check.isPending ? "Kontrollerer …" : "Kontroller tilkoblingen"}
                </Button>
              </div>
              <p className="ek-xs ek-muted">
                {provider.key_configured
                  ? `Kontrollerer den lagrede nøkkelen hos ${provider.name} på nytt.${provider.last_checked_at ? ` Sist kontrollert ${formatDateTime(provider.last_checked_at)}.` : ""}`
                  : "Koble til med en nøkkel først."}
              </p>
            </div>
          </div>
        </Disclosure>
      </div>
    </Card>
  );
}

/** Azure OpenAI and own (local) servers: endpoint, optional key and a manual check. */
function ProviderCard({ provider, discoveryEnabled }: { provider: Provider; discoveryEnabled: boolean }) {
  const refresh = useAiRefresh();
  const toast = useToast();
  const [endpoint, setEndpoint] = useState(provider.endpoint ?? "");
  const [apiVersion, setApiVersion] = useState(provider.api_version ?? "");
  const [key, setKey] = useState("");
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.put<Provider>(`/api/ai/providers/${provider.id}`, body),
    onSuccess: () => {
      setKey("");
      refresh();
    },
  });
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>(`/api/ai/providers/${provider.id}/test`),
    onSettled: refresh,
  });
  const discover = useMutation({
    mutationFn: () => api.post<{ found: number; added: number; note: string | null }>(`/api/ai/providers/${provider.id}/discover`),
    onSuccess: (r) => {
      refresh();
      toast.show({ tone: "info", title: r.added ? `${r.added} nye modeller i listen` : "Ingen nye modeller",
        body: r.note ?? (r.added ? "Nye modeller må klassifiseres før de kan brukes." : undefined) });
    },
  });
  const deleteKey = useMutation({ mutationFn: () => api.delete(`/api/ai/providers/${provider.id}/key`), onSuccess: refresh });
  const needsEndpoint = provider.type !== "anthropic";

  return (
    <Card title={provider.name} headingLevel={3} actions={<ProviderBadges provider={provider} />}>
      <div className="ek-stack">
        <Switch label={`Bruk ${provider.name}`} checked={provider.enabled} onChange={(enabled) => update.mutate({ enabled })} />
        <SwitchNote provider={provider} />
        <form className="ek-stack" onSubmit={(e) => {
          e.preventDefault();
          update.mutate({ endpoint: needsEndpoint ? endpoint : undefined, api_version: provider.type === "azure_openai" ? apiVersion : undefined, api_key: key || undefined });
        }}>
          {needsEndpoint ? (
            <TextField label={provider.type === "azure_openai" ? "Azure-endepunkt" : "Endepunkt"} type="url" value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              hint={provider.type === "openai_compatible" ? "For eksempel http://127.0.0.1:11434/v1 for Ollama." : undefined} />
          ) : null}
          {provider.type === "azure_openai" ? (
            <TextField label="API-versjon" value={apiVersion} onChange={(e) => setApiVersion(e.target.value)} />
          ) : null}
          <TextField label="API-nøkkel" type="password" autoComplete="off" spellCheck={false} value={key}
            onChange={(e) => setKey(e.target.value)} optional={!provider.needs_key}
            placeholder={provider.key_configured ? "Lagret – skriv for å bytte" : ""}
            hint="Nøkkelen lagres bare i Windows Legitimasjonsbehandling og vises aldri igjen." />
          <div className="ek-cluster">
            <Button type="submit" variant="primary" loading={update.isPending}>Lagre</Button>
            <Button icon={<PlugZap aria-hidden="true" />} onClick={() => test.mutate()} loading={test.isPending}>Test tilkobling</Button>
            {discoveryEnabled ? (
              <Button icon={<Search aria-hidden="true" />} onClick={() => discover.mutate()} loading={discover.isPending}>Hent modelliste</Button>
            ) : null}
            {provider.key_configured ? (
              <Button variant="ghost" icon={<Trash aria-hidden="true" />} onClick={() => deleteKey.mutate()} loading={deleteKey.isPending}>
                Fjern nøkkel
              </Button>
            ) : null}
          </div>
        </form>
        <ProviderError provider={provider} />
        {update.error || test.error || discover.error ? (
          <Alert tone="danger" role="alert">{((update.error ?? test.error ?? discover.error) as Error).message}</Alert>
        ) : null}
      </div>
    </Card>
  );
}

function ClassifyDialog({ model, providers, onClose }: { model: Model | null; providers: Provider[]; onClose: () => void }) {
  const refresh = useAiRefresh();
  const isNew = model === null;
  const [form, setForm] = useState({
    provider_id: model?.provider_id ?? providers[0]?.id ?? "", model_id: model?.model_id ?? "", display_name: model?.display_name ?? "",
    vision: model?.vision ?? false, structured_output: model?.structured_output ?? true, context_class: model?.context_class ?? 2,
    quality_class: model?.quality_class ?? 2, speed_class: model?.speed_class ?? 2, cost_class: model?.cost_class ?? 2,
  });
  const save = useMutation({
    mutationFn: () => (isNew ? api.post("/api/ai/models", form) : api.put(`/api/ai/models/${model.id}`, {
      display_name: form.display_name, vision: form.vision, structured_output: form.structured_output,
      context_class: form.context_class, quality_class: form.quality_class, speed_class: form.speed_class, cost_class: form.cost_class,
    })),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  const num = (key: "context_class" | "quality_class" | "speed_class" | "cost_class", label: string, min: number, max: number, hint: string) => (
    <SelectField label={label} hint={hint} value={String(form[key])} onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })}
      options={Array.from({ length: max - min + 1 }, (_, i) => ({ value: String(min + i), label: String(min + i) }))} />
  );
  return (
    <Dialog open onClose={onClose} title={isNew ? "Legg til modell" : `Klassifiser ${model.display_name}`} size="lg"
      description="Klassene er relative og brukes til å velge modell. EmneKlar gjetter dem ikke fra leverandørens modelliste."
      footer={<><Button onClick={onClose}>Avbryt</Button><Button variant="primary" onClick={() => save.mutate()} loading={save.isPending}>Lagre</Button></>}>
      <div className="ek-stack">
        {isNew ? (
          <div className="ek-grid" data-cols="2">
            <SelectField label="Leverandør" value={form.provider_id} onChange={(e) => setForm({ ...form, provider_id: e.target.value })}
              options={providers.map((p) => ({ value: p.id, label: p.name }))} />
            <TextField label="Modell- eller deployment-navn" value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} />
          </div>
        ) : null}
        <TextField label="Visningsnavn" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        <div className="ek-grid" data-cols="2">
          {num("quality_class", "Kvalitet", 1, 4, "1 = enkel, 4 = sterkest")}
          {num("speed_class", "Hastighet", 1, 3, "1 = treg, 3 = rask")}
          {num("cost_class", "Kostnad", 0, 4, "0 = gratis/lokal, 4 = dyrest")}
          {num("context_class", "Kontekst", 1, 4, "1 = opptil ca. 30k tokens, 4 = over ca. 380k")}
        </div>
        <Switch label="Kan tolke bilder" checked={form.vision} onChange={(vision) => setForm({ ...form, vision })} />
        <Switch label="Støtter strukturert svar (JSON-skjema)" checked={form.structured_output}
          onChange={(structured_output) => setForm({ ...form, structured_output })} />
        {save.error ? <Alert tone="danger" role="alert">{(save.error as Error).message}</Alert> : null}
      </div>
    </Dialog>
  );
}

export function AiSettings() {
  const session = useSession();
  const refresh = useAiRefresh();
  const providers = useQuery({ queryKey: ["ai-providers"], queryFn: () => api.get<{ providers: Provider[]; unavailable_reason: string | null; privacy: { allow_external_ai: boolean } }>("/api/ai/providers") });
  const models = useQuery({ queryKey: ["ai-models"], queryFn: () => api.get<{ models: Model[]; catalog_version: string; catalog_note: string }>("/api/ai/models") });
  const routing = useQuery({ queryKey: ["ai-routing"], queryFn: () => api.get<Routing>("/api/ai/routing") });
  const usage = useQuery({ queryKey: ["ai-usage"], queryFn: () => api.get<Usage>("/api/ai/usage?limit=50") });
  const [classify, setClassify] = useState<Model | null | "new">(null);
  const discoveryEnabled = session.flags.ai_model_discovery !== false;
  // The model list is kept fresh in the background (once per visit, only for a connected provider with an old list).
  const refreshModels = useMutation({
    mutationFn: (id: string) => api.post(`/api/ai/providers/${id}/refresh-models`),
    onSuccess: refresh,
  });
  const refreshed = useRef(new Set<string>());
  useEffect(() => {
    for (const p of providers.data?.providers ?? []) {
      if (p.models_stale && discoveryEnabled && !refreshed.current.has(p.id)) {
        refreshed.current.add(p.id);
        refreshModels.mutate(p.id);
      }
    }
  }, [providers.data, discoveryEnabled, refreshModels]);
  const updateModel = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => api.put(`/api/ai/models/${id}`, { enabled }),
    onSuccess: refresh,
  });
  const deleteModel = useMutation({ mutationFn: (id: number) => api.delete(`/api/ai/models/${id}`), onSuccess: refresh });
  const updateRouting = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.put<Routing>("/api/ai/routing", body),
    onSuccess: refresh,
  });

  if (providers.isPending || models.isPending || routing.isPending) return <Spinner label="Henter KI-innstillinger …" />;
  if (providers.error || routing.error) {
    return <Alert tone="danger" role="alert">{((providers.error ?? routing.error) as Error).message}</Alert>;
  }
  const providerList = providers.data.providers;
  const tasks = routing.data.tasks;
  const providerName = (id: string) => providerList.find((p) => p.id === id)?.name ?? id;
  const modelColumns: Column<Model>[] = [
    { key: "name", header: "Modell", rowHeader: true, cell: (m) => (
      <span className="ek-stack" data-gap="1">
        <span>{m.display_name}</span>
        <span className="ek-xs ek-muted">{m.model_id}</span>
        {!m.capabilities_known ? <Badge tone="warning">Må klassifiseres</Badge> : null}
      </span>
    ) },
    { key: "provider", header: "Leverandør", cell: (m) => providerName(m.provider_id) },
    { key: "vision", header: "Bilder", cell: (m) => (m.vision ? "Ja" : "Nei") },
    { key: "quality", header: "Kvalitet", cell: (m) => CLASS(m.quality_class, 4) },
    { key: "speed", header: "Hastighet", cell: (m) => CLASS(m.speed_class, 3) },
    { key: "cost", header: "Kostnad", cell: (m) => CLASS(m.cost_class, 4) },
    { key: "enabled", header: "Aktiv", cell: (m) => (
      <Switch label={<span className="ek-visually-hidden">Bruk {m.display_name}</span>} showState checked={m.enabled}
        disabled={!m.capabilities_known} onChange={(enabled) => updateModel.mutate({ id: m.id, enabled })} />
    ) },
    { key: "actions", header: <span className="ek-visually-hidden">Handlinger</span>, cell: (m) => (
      <div className="ek-cluster" data-gap="1">
        <Button size="sm" onClick={() => setClassify(m)}>Klassifiser<span className="ek-visually-hidden">: {m.display_name}</span></Button>
        {m.source !== "catalog" ? (
          <IconButton size="sm" label={`Slett ${m.display_name}`} onClick={() => deleteModel.mutate(m.id)}><Trash aria-hidden="true" size={14} /></IconButton>
        ) : null}
      </div>
    ) },
  ];

  return (
    <div className="ek-stack" data-gap="6">
      <Alert tone={providers.data.privacy.allow_external_ai ? "info" : "warning"} title="Personvern">
        {providers.data.privacy.allow_external_ai
          ? "Sending av emneinnhold til eksterne KI-tjenester er slått på. Du ser alltid hva som sendes før det skjer, hvis «Bekreft før innhold sendes» er på."
          : "Sending av emneinnhold til eksterne KI-tjenester er slått av. Lokale modeller kan brukes."}{" "}
        <Link to="/innstillinger/sikkerhet-og-personvern">Endre under Sikkerhet og personvern</Link>.
        {providers.data.unavailable_reason ? <p className="ek-mt-2">{providers.data.unavailable_reason}</p> : null}
      </Alert>
      <section className="ek-stack" aria-labelledby="leverandorer">
        <h2 id="leverandorer">Leverandører</h2>
        <p className="ek-small ek-muted">EmneKlar virker uten KI. KI brukes bare til forslag, og alle forslag merkes «KI-forslag – må vurderes».</p>
        {providerList.map((p) => (KEY_PROVIDERS.includes(p.type)
          ? <KeyProviderCard key={p.id} provider={p} />
          : <ProviderCard key={p.id} provider={p} discoveryEnabled={discoveryEnabled} />))}
      </section>

      <Card title="Modellvalg" headingLevel={2}>
        <div className="ek-stack" data-gap="6">
          <RadioGroup legend="Strategi" name="ai-strategy" value={routing.data?.strategy ?? "auto"}
            onChange={(strategy) => updateRouting.mutate({ strategy })}
            options={(routing.data?.strategies ?? []).map((s) => ({
              value: s.id, label: s.id === "auto" ? `${s.label} (anbefalt)` : s.label, hint: STRATEGY_HINTS[s.id],
            }))} />
          {routing.data?.strategy === "manual" ? (
            <div className="ek-grid" data-cols="2">
              {routing.data.tasks.map((t) => (
                <SelectField key={t.key} label={t.label} value={t.manual_model ?? ""} placeholder="Ingen modell valgt"
                  onChange={(e) => updateRouting.mutate({ manual_models: Object.fromEntries(tasks.map((x) => [x.key, x.key === t.key ? e.target.value : (x.manual_model ?? "")])) })}
                  options={(models.data?.models ?? []).filter((m) => m.enabled && (!t.vision || m.vision)).map((m) => ({
                    value: `${m.provider_id}/${m.model_id}`, label: `${m.display_name} (${providerName(m.provider_id)})`,
                  }))} />
              ))}
            </div>
          ) : null}
          <Disclosure summary="Vis detaljer om modellvalget">
            <div className="ek-stack">
              <p className="ek-small ek-muted">For hver oppgave: modellen som velges nå, hvorfor, og hvilke modeller som brukes som reserve.</p>
              <DataTable caption="Modellvalg per oppgave" captionHidden rowKey={(t) => t.key} rows={routing.data?.tasks ?? []}
                columns={[
                  { key: "task", header: "Aktuell oppgave", rowHeader: true, cell: (t) => t.label },
                  { key: "model", header: "Valgt modell", cell: (t) => t.decision.primary?.display_name ?? "Ingen" },
                  { key: "provider", header: "Leverandør", cell: (t) => (t.decision.primary ? providerName(t.decision.primary.provider_id) : "–") },
                  { key: "reason", header: "Begrunnelse", cell: (t) => <span className="ek-small">{t.decision.reason}</span> },
                  { key: "fallback", header: "Reserve", cell: (t) => t.decision.fallbacks.map((f) => f.display_name).join(", ") || "–" },
                  { key: "prefer", header: "Foretrukket leverandør", cell: (t) => (
                    <SelectField label={`Foretrukket leverandør for ${t.label}`} hideLabel value={t.preferred_provider ?? ""} placeholder="Ingen"
                      onChange={(e) => updateRouting.mutate({ task_providers: Object.fromEntries(tasks.map((x) => [x.key, x.key === t.key ? e.target.value : (x.preferred_provider ?? "")])) })}
                      options={providerList.filter((p) => p.enabled).map((p) => ({ value: p.id, label: p.name }))} />
                  ) },
                ]} />
            </div>
          </Disclosure>
          {updateRouting.error ? <Alert tone="danger" role="alert">{(updateRouting.error as Error).message}</Alert> : null}
        </div>
      </Card>

      <Card title="Modeller" headingLevel={2}
        actions={<Button size="sm" icon={<Plus aria-hidden="true" />} onClick={() => setClassify("new")}>Legg til modell</Button>}>
        <div className="ek-stack">
          <p className="ek-xs ek-muted">{models.data?.catalog_note} (startliste {models.data?.catalog_version})</p>
          <DataTable caption="Modeller" captionHidden columns={modelColumns} rows={models.data?.models ?? []} rowKey={(m) => m.id} />
        </div>
      </Card>

      <Card title="Bruk av KI" headingLevel={2}>
        <p className="ek-small ek-muted">Loggen viser bare metadata – aldri innholdet som ble sendt.</p>
        {usage.data?.items.length ? (
          <DataTable caption="Siste KI-kall" captionHidden rowKey={(u) => u.id} rows={usage.data.items}
            columns={[
              { key: "time", header: "Tid", cell: (u) => formatDateTime(u.created_at) },
              { key: "task", header: "Oppgave", rowHeader: true, cell: (u) => u.task_label },
              { key: "model", header: "Modell", cell: (u) => `${u.model_id} (${providerName(u.provider_id)})` },
              { key: "result", header: "Resultat", cell: (u) => (u.success ? <Badge tone="success">OK</Badge> : <Badge tone="danger">{u.error_code ?? "Feil"}</Badge>) },
              { key: "fallback", header: "Reserve brukt", cell: (u) => (u.fallback_used ? "Ja" : "Nei") },
              { key: "tokens", header: "Tokens inn/ut", numeric: true, cell: (u) => `${formatNumber(u.input_tokens)} / ${formatNumber(u.output_tokens)}` },
              { key: "summary", header: "Sendt", cell: (u) => <span className="ek-small">{u.summary ?? "–"}</span> },
            ]} />
        ) : <p className="ek-small ek-mt-2">Ingen KI-kall ennå.</p>}
      </Card>
      {classify !== null ? (
        <ClassifyDialog model={classify === "new" ? null : classify} providers={providerList} onClose={() => setClassify(null)} />
      ) : null}
    </div>
  );
}

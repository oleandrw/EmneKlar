// Innstillinger: Analyse, Sikkerhet og personvern, Utseende, Varsler, Avanserte innstillinger.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, FolderOpen, LogOut, RotateCcw } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { api } from "../../core/api/client";
import { DOMAIN_LABEL, type AnalysisDomain } from "../../core/labels";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  DataTable,
  Disclosure,
  Fieldset,
  RadioGroup,
  SelectField,
  Spinner,
  Switch,
  TextField,
  useToast,
} from "../../design-system";
import { useSaveSettings, type AppSettings, type FlagInfo, type Section } from "./api";

/** A settings form with local state, a dirty marker and one «Lagre» button. */
function useSectionForm<T extends object>(section: Section, initial: T) {
  const save = useSaveSettings(section);
  const [form, setForm] = useState<T>(initial);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(form as Record<string, unknown>);
  };
  return { form, setForm, dirty, save, onSubmit };
}

function SaveRow({ dirty, saving, error }: { dirty: boolean; saving: boolean; error: unknown }) {
  return (
    <>
      {error ? <Alert tone="danger" role="alert">{(error as Error).message}</Alert> : null}
      <div className="ek-cluster">
        <Button type="submit" variant="primary" loading={saving} disabled={!dirty}>Lagre</Button>
        {dirty ? <Badge tone="warning">Ikke lagret</Badge> : null}
      </div>
    </>
  );
}

function NumberField({ label, value, min, max, hint, onChange }: { label: string; value: number; min: number; max: number; hint?: ReactNode; onChange: (n: number) => void }) {
  return <TextField label={label} type="number" min={min} max={max} value={value} hint={hint} onChange={(e) => onChange(Number(e.target.value))} />;
}

/* -------------------------------------------------------------------------------- Analyse */

interface Profiles {
  selected: string;
  profiles: { id: string; title: string; description: string; is_legal_requirement: boolean; verified_at: string; criteria_count: number }[];
}

export function AnalysisSettings({ settings }: { settings: AppSettings }) {
  const { form, setForm, dirty, save, onSubmit } = useSectionForm("analysis", settings.analysis);
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<Profiles>("/api/accessibility/profiles") });
  const domains: AnalysisDomain[] = ["accessibility", "content_quality", "structure", "quiz"];
  return (
    <Card title="Analyse" headingLevel={2}>
      <form className="ek-stack" data-gap="6" onSubmit={onSubmit}>
        <Fieldset legend="Forhåndsvalgte analyseområder" hint="Brukes i «Kjør ny analyse». Quizkvalitet er av som standard.">
          {domains.map((d) => (
            <Checkbox key={d} label={DOMAIN_LABEL[d]} checked={form.default_domains.includes(d)}
              onChange={(e) => setForm({ ...form, default_domains: e.target.checked ? [...form.default_domains, d] : form.default_domains.filter((x) => x !== d) })} />
          ))}
        </Fieldset>
        {profiles.data ? (
          <RadioGroup legend="Regulatorisk profil for universell utforming" name="profile" variant="card" value={form.regulatory_profile}
            hint="Bestemmer hvilken juridisk status funnene vises med. Selve kontrollene er de samme."
            onChange={(regulatory_profile) => setForm({ ...form, regulatory_profile })}
            options={profiles.data.profiles.map((p) => ({
              value: p.id, label: p.title,
              hint: `${p.description} ${p.criteria_count} suksesskriterier. Kontrollert ${p.verified_at}.`,
            }))} />
        ) : <Spinner label="Henter profiler …" />}
        <Fieldset legend="Lenker">
          <Checkbox label="Kontroller eksterne lenker" checked={form.check_external_links}
            onChange={(e) => setForm({ ...form, check_external_links: e.target.checked })} />
          <div className="ek-grid" data-cols="2">
            <NumberField label="Tidsavbrudd (sekunder)" value={form.link_timeout_seconds} min={3} max={60} onChange={(link_timeout_seconds) => setForm({ ...form, link_timeout_seconds })} />
            <NumberField label="Samtidige lenkesjekker" value={form.link_concurrency} min={1} max={16} onChange={(link_concurrency) => setForm({ ...form, link_concurrency })} />
            <NumberField label="Samtidige sjekker per nettsted" value={form.link_per_host} min={1} max={4} onChange={(link_per_host) => setForm({ ...form, link_per_host })} />
            <NumberField label="Gjenbruk resultater (timer)" value={form.link_cache_hours} min={0} max={336}
              hint="0 betyr at alle lenker sjekkes på nytt hver gang." onChange={(link_cache_hours) => setForm({ ...form, link_cache_hours })} />
          </div>
        </Fieldset>
        <Fieldset legend="Dokumenter">
          <Checkbox label="Kontroller PDF-, Word-, PowerPoint- og Excel-filer" checked={form.check_documents}
            onChange={(e) => setForm({ ...form, check_documents: e.target.checked })} />
          <NumberField label="Største fil som kontrolleres (MB)" value={form.max_document_mb} min={1} max={200}
            onChange={(max_document_mb) => setForm({ ...form, max_document_mb })} />
        </Fieldset>
        <Fieldset legend="Canvas">
          <Checkbox label="Ta med upublisert innhold" checked={form.include_unpublished}
            hint="Upublisert innhold er ikke synlig for studentene, men bør ofte rettes før det publiseres."
            onChange={(e) => setForm({ ...form, include_unpublished: e.target.checked })} />
          <NumberField label="Samtidige forespørsler til Canvas" value={form.canvas_concurrency} min={1} max={6}
            hint="Lavere tall belaster Canvas mindre. EmneKlar bremser også automatisk når Canvas ber om det."
            onChange={(canvas_concurrency) => setForm({ ...form, canvas_concurrency })} />
        </Fieldset>
        <SaveRow dirty={dirty} saving={save.isPending} error={save.error} />
      </form>
    </Card>
  );
}

/* ----------------------------------------------------------------- Sikkerhet og personvern */

interface Storage {
  data_dir: string;
  database: string;
  folders: { key: string; label: string; path: string; size: number; files: number }[];
  counts: Record<string, number>;
}

const CLEAR_TEXT: Record<"cache" | "analysis" | "reports", { label: string; body: string }> = {
  cache: { label: "Tøm hurtigbuffer", body: "Lagrede lenkesjekker og midlertidige filer slettes. Neste analyse sjekker alle lenker på nytt." },
  analysis: { label: "Slett analyser og funn", body: "Alle lagrede analyser, funn og «ignorert»-valg slettes fra denne maskinen. Endringslogg og sikkerhetskopier beholdes. Ingenting i Canvas endres." },
  reports: { label: "Slett rapporter", body: "Alle rapportfiler slettes fra denne maskinen." },
};

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} kB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function PrivacySettings({ settings }: { settings: AppSettings }) {
  const save = useSaveSettings("privacy");
  const client = useQueryClient();
  const toast = useToast();
  const [retention, setRetention] = useState(settings.privacy.snapshot_retention_days);
  const [clearing, setClearing] = useState<"cache" | "analysis" | "reports" | null>(null);
  const storage = useQuery({ queryKey: ["storage"], queryFn: () => api.get<Storage>("/api/system/storage") });
  const clear = useMutation({
    mutationFn: (target: string) => api.post<Storage>("/api/system/storage/clear", { target }),
    onSuccess: (data) => {
      client.setQueryData(["storage"], data);
      setClearing(null);
      void client.invalidateQueries({ queryKey: ["findings"] });
      void client.invalidateQueries({ queryKey: ["overview"] });
      toast.show({ tone: "success", title: "Lokale data er slettet" });
    },
  });
  const open = useMutation({ mutationFn: (folder: string) => api.post("/api/system/open-folder", { folder }) });
  const logout = useMutation({ mutationFn: () => api.post("/api/session/logout"), onSuccess: () => window.location.reload() });

  return (
    <div className="ek-stack" data-gap="6">
      <Card title="KI og personvern" headingLevel={2}>
        <div className="ek-stack">
          <Switch label="Tillat sending av emneinnhold til ekstern KI" checked={settings.privacy.allow_external_ai}
            onChange={(allow_external_ai) => save.mutate({ allow_external_ai })} />
          <Switch label="Bekreft før innhold sendes" checked={settings.privacy.confirm_before_send}
            onChange={(confirm_before_send) => save.mutate({ confirm_before_send })} />
          <p className="ek-small">
            Når bekreftelse er på, ser du alltid en oppsummering av hva som sendes (for eksempel «3 Canvas-sider og 2
            bilder sendes») før noe sendes. Lokale modeller på denne maskinen kan brukes selv om ekstern KI er av.
          </p>
          <Disclosure summary="Dette sendes aldri til KI">
            <ul className="ek-small">
              <li>Studentenes innleveringer, karakterer eller meldinger</li>
              <li>Unødvendige personopplysninger</li>
              <li>Canvas-token eller API-nøkler</li>
            </ul>
          </Disclosure>
          {save.error ? <Alert tone="danger" role="alert">{(save.error as Error).message}</Alert> : null}
        </div>
      </Card>

      <Card title="Hemmeligheter og økt" headingLevel={2}>
        <div className="ek-stack">
          <p className="ek-small">
            Canvas-token og API-nøkler lagres bare i Windows Legitimasjonsbehandling – aldri i filer, i databasen, i
            nettleseren eller i logger. EmneKlar kjører bare på denne maskinen (127.0.0.1) og kan ikke nås fra nettverket.
          </p>
          <div>
            <Button icon={<LogOut aria-hidden="true" />} onClick={() => logout.mutate()} loading={logout.isPending}>Logg ut av denne økten</Button>
          </div>
          <p className="ek-xs ek-muted">Etter utlogging åpner du EmneKlar igjen med start.bat.</p>
        </div>
      </Card>

      <Card title="Lokale data" headingLevel={2}>
        <div className="ek-stack">
          {storage.isPending ? <Spinner label="Henter oversikt …" /> : null}
          {storage.data ? (
            <>
              <p className="ek-small">Alle data lagres i <code>{storage.data.data_dir}</code>, adskilt fra programmet.</p>
              <DataTable caption="Lagring" captionHidden rowKey={(f) => f.key} rows={storage.data.folders}
                columns={[
                  { key: "label", header: "Hva", rowHeader: true, cell: (f) => f.label },
                  { key: "size", header: "Størrelse", numeric: true, cell: (f) => formatSize(f.size) },
                  { key: "open", header: <span className="ek-visually-hidden">Handling</span>, cell: (f) => (
                    f.key === "cache" ? null : (
                      <Button size="sm" icon={<FolderOpen aria-hidden="true" />} onClick={() => open.mutate(f.key)}>
                        Åpne mappen<span className="ek-visually-hidden">: {f.label}</span>
                      </Button>
                    )
                  ) },
                ]} />
              {open.error ? <Alert tone="info">{(open.error as Error).message}</Alert> : null}
            </>
          ) : null}
          <form className="ek-cluster" data-align="end" onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ snapshot_retention_days: retention });
          }}>
            <div style={{ minWidth: "14rem" }}>
              <NumberField label="Behold nedlastet emneinnhold i (dager)" value={retention} min={1} max={3650}
                hint="Den nyeste kopien av hvert emne beholdes alltid." onChange={setRetention} />
            </div>
            <Button type="submit" disabled={retention === settings.privacy.snapshot_retention_days} loading={save.isPending}>Lagre</Button>
          </form>
          <div className="ek-cluster">
            {(Object.keys(CLEAR_TEXT) as (keyof typeof CLEAR_TEXT)[]).map((key) => (
              <Button key={key} variant="danger" onClick={() => setClearing(key)}>{CLEAR_TEXT[key].label}</Button>
            ))}
          </div>
        </div>
      </Card>
      <ConfirmDialog
        open={clearing !== null}
        onClose={() => setClearing(null)}
        onConfirm={() => clearing && clear.mutate(clearing)}
        title={clearing ? `${CLEAR_TEXT[clearing].label}?` : ""}
        confirmLabel={clearing ? CLEAR_TEXT[clearing].label : ""}
        danger
        loading={clear.isPending}
      >
        <p>{clearing ? CLEAR_TEXT[clearing].body : null}</p>
        {clear.error ? <Alert tone="danger" role="alert">{(clear.error as Error).message}</Alert> : null}
      </ConfirmDialog>
    </div>
  );
}

/* --------------------------------------------------------------------------------- Utseende */

export function AppearanceSettings({ settings }: { settings: AppSettings }) {
  const { form, setForm, dirty, save, onSubmit } = useSectionForm("appearance", settings.appearance);
  return (
    <Card title="Utseende" headingLevel={2}>
      <form className="ek-stack" data-gap="6" onSubmit={onSubmit}>
        <p className="ek-small ek-muted">Tema (lyst/mørkt) velges under Generelt.</p>
        <RadioGroup legend="Tekststørrelse" name="text-size" value={form.text_size} onChange={(text_size) => setForm({ ...form, text_size })}
          options={[{ value: "normal", label: "Normal" }, { value: "large", label: "Stor" }, { value: "larger", label: "Større" }]} />
        <RadioGroup legend="Tetthet" name="density" value={form.density} onChange={(density) => setForm({ ...form, density })}
          options={[{ value: "comfortable", label: "Luftig" }, { value: "compact", label: "Kompakt" }]} />
        <RadioGroup legend="Bevegelse" name="motion" value={form.reduce_motion} onChange={(reduce_motion) => setForm({ ...form, reduce_motion })}
          options={[{ value: "system", label: "Følg innstillingen i Windows" }, { value: "always", label: "Reduser alltid bevegelse" }]} />
        <Checkbox label="Understrek lenker" checked={form.underline_links} hint="Gjør lenker lettere å skille fra vanlig tekst."
          onChange={(e) => setForm({ ...form, underline_links: e.target.checked })} />
        <SaveRow dirty={dirty} saving={save.isPending} error={save.error} />
      </form>
    </Card>
  );
}

/* ---------------------------------------------------------------------------------- Varsler */

export function NotificationSettings({ settings }: { settings: AppSettings }) {
  const save = useSaveSettings("notifications");
  const [permission, setPermission] = useState<string>(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  const toggleBrowser = async (enabled: boolean) => {
    if (enabled && typeof Notification !== "undefined" && Notification.permission !== "granted") {
      const result = await Notification.requestPermission();
      setPermission(result);
      if (result !== "granted") return;
    }
    save.mutate({ browser_notifications: enabled });
  };
  return (
    <Card title="Varsler" headingLevel={2}>
      <div className="ek-stack">
        <Switch label="Vis varsel i EmneKlar når en analyse er ferdig" checked={settings.notifications.notify_job_complete}
          onChange={(notify_job_complete) => save.mutate({ notify_job_complete })} />
        <Switch label="Vis også varsel fra Windows når EmneKlar ikke er i fokus" checked={settings.notifications.browser_notifications}
          disabled={permission === "unsupported"} onChange={(enabled) => void toggleBrowser(enabled)} />
        {permission === "denied" ? (
          <Alert tone="info">Nettleseren har blokkert varsler for EmneKlar. Tillat varsler i nettleserens innstillinger for nettstedet.</Alert>
        ) : null}
        {permission === "unsupported" ? <p className="ek-small ek-muted">Nettleseren støtter ikke varsler.</p> : null}
        {save.error ? <Alert tone="danger" role="alert">{(save.error as Error).message}</Alert> : null}
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------------ Avanserte innstillinger */

const STAGE: Record<FlagInfo["stage"], { label: string; tone: "success" | "info" | "warning" }> = {
  stable: { label: "Stabil", tone: "success" },
  beta: { label: "Beta", tone: "info" },
  experimental: { label: "Eksperimentell", tone: "warning" },
};

export function AdvancedSettings({ settings, flags }: { settings: AppSettings; flags: FlagInfo[] }) {
  const client = useQueryClient();
  const toast = useToast();
  const initial = {
    update_repository: settings.advanced.update_repository ?? "", update_channel: settings.advanced.update_channel,
    check_updates: settings.advanced.check_updates, debug_logging: settings.advanced.debug_logging,
  };
  const { form, setForm, dirty, save, onSubmit } = useSectionForm("advanced", initial);
  const setFlag = useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean | null }) => api.put(`/api/flags/${key}`, { enabled }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["settings"] });
      void client.invalidateQueries({ queryKey: ["session"] });
    },
  });
  const log = useQuery({ queryKey: ["system-log"], queryFn: () => fetch("/api/system/log?lines=300", { credentials: "same-origin" }).then((r) => r.text()), enabled: false });

  return (
    <div className="ek-stack" data-gap="6">
      <Card title="Funksjonsflagg" headingLevel={2}>
        <p className="ek-small ek-muted">Slå funksjoner av eller på. Beta- og eksperimentelle funksjoner kan endre seg.</p>
        <ul className="ek-list-reset ek-divider-list ek-mt-4">
          {flags.map((flag) => (
            <li key={flag.key} className="ek-row">
              <div className="ek-row__main">
                <div className="ek-cluster" data-gap="2">
                  <Switch label={flag.name} checked={flag.enabled} onChange={(enabled) => setFlag.mutate({ key: flag.key, enabled })} />
                  <Badge tone={STAGE[flag.stage].tone}>{STAGE[flag.stage].label}</Badge>
                </div>
                <span className="ek-xs ek-muted">{flag.description}</span>
              </div>
              {flag.overridden ? (
                <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden="true" />} onClick={() => setFlag.mutate({ key: flag.key, enabled: null })}>
                  Tilbakestill<span className="ek-visually-hidden">: {flag.name}</span>
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
        {setFlag.error ? <Alert tone="danger" role="alert">{(setFlag.error as Error).message}</Alert> : null}
      </Card>

      <Card title="Oppdateringer" headingLevel={2}>
        <form className="ek-stack" onSubmit={onSubmit}>
          <TextField label="GitHub-repository for oppdateringer" placeholder="eier/EmneKlar" value={form.update_repository}
            hint="La stå tomt for å bruke repositoriet EmneKlar ble installert fra (hvis kjent). Eneste data som sendes til GitHub, er en forespørsel om siste versjon."
            onChange={(e) => setForm({ ...form, update_repository: e.target.value })} />
          <SelectField label="Kanal" value={form.update_channel} onChange={(e) => setForm({ ...form, update_channel: e.target.value as "stable" | "prerelease" })}
            options={[{ value: "stable", label: "Stabile versjoner" }, { value: "prerelease", label: "Også forhåndsversjoner" }]} />
          <Checkbox label="Se etter oppdateringer automatisk (høyst én gang i døgnet)" checked={form.check_updates}
            onChange={(e) => setForm({ ...form, check_updates: e.target.checked })} />
          <Checkbox label="Detaljert logging (for feilsøking)" checked={form.debug_logging}
            hint="Loggen inneholder aldri token, nøkler eller emneinnhold." onChange={(e) => setForm({ ...form, debug_logging: e.target.checked })} />
          <SaveRow dirty={dirty} saving={save.isPending} error={save.error} />
        </form>
      </Card>

      <Card title="Feilsøkingslogg" headingLevel={2}>
        <div className="ek-stack">
          <p className="ek-small ek-muted">De siste linjene fra loggen. Sensitive verdier er fjernet før de ble skrevet.</p>
          <div className="ek-cluster">
            <Button onClick={() => void log.refetch()} loading={log.isFetching}>Vis loggen</Button>
            {log.data ? (
              <Button icon={<Copy aria-hidden="true" />} onClick={() => {
                void navigator.clipboard.writeText(log.data ?? "").then(() => toast.show({ tone: "success", title: "Loggen er kopiert" }));
              }}>
                Kopier
              </Button>
            ) : null}
          </div>
          {log.data !== undefined ? <pre className="ek-code-block" aria-label="Logg">{log.data || "Loggen er tom."}</pre> : null}
        </div>
      </Card>
    </div>
  );
}

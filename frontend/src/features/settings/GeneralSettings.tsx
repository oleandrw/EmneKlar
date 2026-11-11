import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import { useCourses } from "../../core/course";
import { formatDateTime } from "../../core/format";
import { PRIMARY_NAV } from "../../core/layout/nav";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  Disclosure,
  ExternalLink,
  KeyValue,
  SelectField,
  Spinner,
  TextField,
} from "../../design-system";
import { useSaveSettings, type AppSettings } from "./api";

export interface UpdateStatus {
  current_version: string;
  install: { type: "git" | "release" | "source"; label: string; path: string; branch: string | null; can_start_from_app: boolean };
  repository: string | null;
  /** The standard source (used when the setting is empty): where EmneKlar was installed from, if known. */
  default_repository: string | null;
  default_repository_source: string;
  /** Another source than the standard one is chosen in Innstillinger. */
  repository_is_custom: boolean;
  channel: string;
  check_enabled: boolean;
  last_checked_at: string | null;
  last_error: string | null;
  latest: { version: string; name: string | null; notes: string; url: string | null; published_at: string | null } | null;
  update_available: boolean;
  is_major: boolean;
  checking: boolean;
  changelog: { version: string; title: string; body: string }[];
}

export function UpdatePanel() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["update-status"], queryFn: () => api.get<UpdateStatus>("/api/updates/status") });
  const check = useMutation({
    mutationFn: () => api.post<UpdateStatus>("/api/updates/check"),
    onSuccess: (data) => client.setQueryData(["update-status"], data),
  });
  const [confirm, setConfirm] = useState(false);
  const [majorOk, setMajorOk] = useState(false);
  const start = useMutation({
    mutationFn: () => api.post<{ started: boolean; message: string }>("/api/updates/start", { confirm_major: majorOk }),
    onSuccess: () => setConfirm(false),
  });
  if (status.isPending) return <Spinner label="Henter versjonsinformasjon …" />;
  if (status.error) return <Alert tone="danger" role="alert">{(status.error as Error).message}</Alert>;
  const s = status.data;
  return (
    <Card title="Versjon og oppdateringer" headingLevel={2}>
      <div className="ek-stack">
        <KeyValue items={[
          ["EmneKlar-versjon", s.current_version],
          ["Installasjon", `${s.install.label}${s.install.branch ? ` (gren ${s.install.branch})` : ""}`],
          ["Oppdateringskilde", s.repository ? `github.com/${s.repository}` : "Ikke satt"],
          ["Siste versjon", s.latest ? `${s.latest.version}${s.latest.published_at ? ` (${formatDateTime(s.latest.published_at)})` : ""}` : "Ukjent"],
          ["Sist sjekket", s.last_checked_at ? formatDateTime(s.last_checked_at) : "Aldri"],
        ]} />
        {!s.repository ? (
          <Alert tone="info" title="Oppdateringskilde mangler">
            EmneKlar vet ikke hvor nye versjoner publiseres. Angi GitHub-repositoriet under{" "}
            <Link to="/innstillinger/avanserte-innstillinger">Avanserte innstillinger</Link>.
          </Alert>
        ) : null}
        {s.last_error ? <Alert tone="warning" title="Siste sjekk feilet">{s.last_error}</Alert> : null}
        {s.update_available && s.latest ? (
          <Alert tone={s.is_major ? "warning" : "success"} title={`Versjon ${s.latest.version} er tilgjengelig`}>
            {s.is_major ? "Dette er en større oppdatering som kan endre hvordan EmneKlar virker. Les endringene først. " : null}
            {s.latest.url ? <ExternalLink href={s.latest.url}>Se utgivelsen på GitHub</ExternalLink> : null}
          </Alert>
        ) : s.latest ? (
          <p className="ek-small">Du har siste versjon.</p>
        ) : null}
        {s.latest?.notes ? (
          <Disclosure summary={`Endringer i ${s.latest.version}`}>
            <pre className="ek-code-block">{s.latest.notes}</pre>
          </Disclosure>
        ) : null}
        <div className="ek-cluster">
          <Button icon={<RefreshCw aria-hidden="true" />} onClick={() => check.mutate()} loading={check.isPending || s.checking}
            disabled={!s.repository}>
            Se etter oppdateringer
          </Button>
          {s.update_available ? (
            s.install.can_start_from_app ? (
              <Button variant="primary" icon={<Download aria-hidden="true" />} onClick={() => setConfirm(true)}>
                Oppdater nå
              </Button>
            ) : (
              <span className="ek-small">Kjør <strong>update.bat</strong> i EmneKlar-mappen for å oppdatere.</span>
            )
          ) : null}
        </div>
        {check.error ? <Alert tone="danger" role="alert">{(check.error as Error).message}</Alert> : null}
        {start.data ? <Alert tone="success" role="status">{start.data.message}</Alert> : null}
        <Disclosure summary="Endringslogg for EmneKlar">
          <div className="ek-stack">
            {s.changelog.map((section) => (
              <div key={section.version} className="ek-stack" data-gap="1">
                <h3>{section.version}{section.title ? ` – ${section.title}` : ""}</h3>
                <pre className="ek-code-block">{section.body}</pre>
              </div>
            ))}
          </div>
        </Disclosure>
      </div>
      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => start.mutate()}
        title="Oppdatere EmneKlar nå?"
        confirmLabel="Start oppdateringen"
        loading={start.isPending}
        confirmDisabled={s.is_major && !majorOk}
      >
        <p>
          Oppdateringen kjører i et eget vindu. EmneKlar stoppes, databasen sikkerhetskopieres, og den nye versjonen
          installeres og kontrolleres før programmet starter igjen. Går noe galt, settes forrige versjon tilbake.
        </p>
        {s.is_major ? (
          <Checkbox label="Jeg har lest endringene og vil oppdatere til en ny hovedversjon" checked={majorOk}
            onChange={(e) => setMajorOk(e.target.checked)} />
        ) : null}
        {start.error ? <Alert tone="danger" role="alert">{(start.error as Error).message}</Alert> : null}
      </ConfirmDialog>
    </Card>
  );
}

export function GeneralSettings({ settings }: { settings: AppSettings }) {
  const save = useSaveSettings("general");
  const courses = useCourses();
  const [form, setForm] = useState(settings.general);
  const changed = JSON.stringify(form) !== JSON.stringify(settings.general);
  return (
    <div className="ek-stack" data-gap="6">
      <Card title="Generelt" headingLevel={2}>
        <form className="ek-stack" onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ theme: form.theme, start_page: form.start_page, default_course_id: form.default_course_id ?? "", page_size: form.page_size });
        }}>
          <TextField label="Språk" value="Norsk bokmål" readOnly hint="EmneKlar finnes på norsk bokmål i denne versjonen." />
          <SelectField label="Tema" value={form.theme} onChange={(e) => setForm({ ...form, theme: e.target.value as AppSettings["general"]["theme"] })}
            options={[{ value: "light", label: "Lyst" }, { value: "dark", label: "Mørkt" }, { value: "system", label: "Følg innstillingen i Windows" }]} />
          <SelectField label="Startside" value={form.start_page} onChange={(e) => setForm({ ...form, start_page: e.target.value })}
            options={PRIMARY_NAV.map((item) => ({ value: item.to.replace(/^\//, ""), label: item.label }))} />
          <SelectField label="Standardemne" value={form.default_course_id ?? ""} placeholder="Ingen"
            hint="Emnet som velges når EmneKlar starter."
            onChange={(e) => setForm({ ...form, default_course_id: e.target.value || null })}
            options={(courses.data?.courses ?? []).map((c) => ({ value: c.id, label: `${c.course_code ?? ""} ${c.name}`.trim() }))} />
          <SelectField label="Funn per side" value={String(form.page_size)} onChange={(e) => setForm({ ...form, page_size: Number(e.target.value) })}
            options={[10, 25, 50, 100].map((n) => ({ value: String(n), label: String(n) }))} />
          {save.error ? <Alert tone="danger" role="alert">{(save.error as Error).message}</Alert> : null}
          <div className="ek-cluster">
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!changed}>Lagre</Button>
            {changed ? <Badge tone="warning">Ikke lagret</Badge> : null}
          </div>
        </form>
      </Card>
      <UpdatePanel />
    </div>
  );
}

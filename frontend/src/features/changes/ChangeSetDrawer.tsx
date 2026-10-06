import { useEffect, useMemo, useState } from "react";

import type { Job } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { RISK, UNDO } from "../../core/labels";
import { useSession } from "../../core/session";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  ConfirmDialog,
  Dialog,
  Disclosure,
  EmptyState,
  ExternalLink,
  Spinner,
  TextField,
  useToast,
} from "../../design-system";
import { FINAL_STATUSES, useJob } from "../analysis/useJob";
import { useChangeMutations, useChanges, type Change } from "./api";
import { ChangePreview } from "./ChangePreview";

const STATUS: Record<Change["status"], { label: string; tone: "neutral" | "info" | "success" | "warning" | "danger" | "violet" }> = {
  staged: { label: "Klar til godkjenning", tone: "info" },
  approved: { label: "Godkjent", tone: "success" },
  applying: { label: "Gjennomføres", tone: "info" },
  applied: { label: "Gjennomført", tone: "success" },
  failed: { label: "Feilet", tone: "danger" },
  conflict: { label: "Konflikt", tone: "warning" },
  discarded: { label: "Fjernet", tone: "neutral" },
  undone: { label: "Angret", tone: "neutral" },
};

const RESULT_TEXT: Record<string, string> = {
  applied: "Gjennomført",
  dry_run: "Dry run – ikke sendt",
  conflict: "Konflikt – innholdet var endret i Canvas",
  failed: "Feilet",
};

const EDIT_LABELS: Record<string, string> = { name: "Navn", title: "Tittel" };

/** «Rediger» for editable changes with simple text values (for example a new module name). */
function EditChange({ change, onSave, saving }: { change: Change; onSave: (proposed: Record<string, unknown>) => void; saving: boolean }) {
  const fields = Object.entries(change.proposed).filter(([key, value]) => typeof value === "string" && key in EDIT_LABELS);
  const [values, setValues] = useState<Record<string, string>>(Object.fromEntries(fields.map(([k, v]) => [k, String(v)])));
  if (!fields.length) return null;
  return (
    <form className="ek-stack" data-gap="2" onSubmit={(e) => {
      e.preventDefault();
      onSave({ ...change.proposed, ...values });
    }}>
      {fields.map(([key]) => (
        <TextField key={key} label={EDIT_LABELS[key]} value={values[key] ?? ""} maxLength={255}
          onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
      ))}
      <div><Button size="sm" type="submit" variant="primary" loading={saving}>Lagre endringen</Button></div>
    </form>
  );
}

export function ChangeSetDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const session = useSession();
  const toast = useToast();
  const { courseId } = useCurrentCourse();
  const changes = useChanges(courseId, open);
  const m = useChangeMutations();
  const [selected, setSelected] = useState<number[]>([]);
  const [preview, setPreview] = useState<Change | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<{ ids: number[] } | null>(null);
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);

  const items = useMemo(() => changes.data?.items ?? [], [changes.data]);
  useEffect(() => setSelected((cur) => cur.filter((id) => items.some((c) => c.id === id))), [items]);
  useEffect(() => {
    if (job.data && FINAL_STATUSES.has(job.data.status)) m.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data?.status]);

  const approved = items.filter((c) => c.status === "approved").map((c) => c.id);
  const startApply = (ids: number[]) => {
    const highRisk = items.filter((c) => ids.includes(c.id) && c.requires_confirmation);
    if (highRisk.length) {
      setConfirmChecked(false);
      setConfirm({ ids });
      return;
    }
    runApply(ids, false);
  };
  const runApply = (ids: number[], confirmed: boolean) =>
    m.apply.mutate(
      { ids, confirm: confirmed },
      {
        onSuccess: (created: Job) => {
          setJobId(created.id);
          setSelected([]);
        },
        onError: (error) => toast.show({ tone: "danger", title: "Kunne ikke starte", body: (error as Error).message }),
      },
    );

  const results = (job.data?.result as { results?: { change_id: number; status: string; message?: string }[] } | undefined)?.results;
  const running = job.data && !FINAL_STATUSES.has(job.data.status);

  return (
    <Dialog open={open} onClose={onClose} variant="drawer" size="lg" title="Endringskø"
      description="Godkjente forslag samles her før noe sendes til Canvas.">
      <div className="ek-stack" data-gap="6">
        {session.dry_run ? (
          <Alert tone="warning" title="Dry run er på">
            Du kan forhåndsvise, godkjenne og «gjennomføre», men ingenting sendes til Canvas. Resultatet logges som Dry run.
          </Alert>
        ) : null}
        {changes.isPending ? <Spinner label="Henter endringer …" /> : null}
        {changes.error ? <Alert tone="danger">{(changes.error as Error).message}</Alert> : null}

        {running ? (
          <Alert tone="info" title="Gjennomfører endringer …" role="status">
            {job.data?.progress.done ?? 0} av {job.data?.progress.total ?? 0} ferdig. Endringer avbrytes aldri midt i en
            skriving.
          </Alert>
        ) : null}
        {results && job.data && FINAL_STATUSES.has(job.data.status) ? (
          <Alert tone="success" title="Resultat" role="status">
            <ul>
              {results.map((r) => (
                <li key={r.change_id}>
                  Endring {r.change_id}: {RESULT_TEXT[r.status] ?? r.status}
                  {r.message && r.status !== "applied" ? ` – ${r.message}` : ""}
                </li>
              ))}
            </ul>
          </Alert>
        ) : null}

        {changes.data && items.length === 0 ? (
          <EmptyState title="Ingen endringer i kø" headingLevel={3}>
            Forslag du legger til fra funn og verktøy, vises her. Ingenting sendes til Canvas før du gjennomfører.
          </EmptyState>
        ) : null}

        {changes.data && items.length > 0 ? (
          <>
            <ul className="ek-cluster ek-list-reset" aria-label="Endringer per område">
              {changes.data.groups.map((g) => (
                <li key={g.domain}>
                  <Badge tone="info">
                    {g.count} {g.label}
                  </Badge>
                </li>
              ))}
            </ul>
            <div className="ek-cluster">
              <Button variant="primary" disabled={!approved.length || Boolean(running)} onClick={() => startApply(approved)}>
                Gjennomfør alle godkjente ({approved.length})
              </Button>
              <Button disabled={!selected.length || Boolean(running)} onClick={() => startApply(selected)}>
                Gjennomfør valgte ({selected.length})
              </Button>
              <Button disabled={!selected.length} onClick={() => m.approve.mutate(selected)} loading={m.approve.isPending}>
                Godkjenn valgte
              </Button>
              <Button disabled={!selected.length} onClick={() => m.conflicts.mutate(selected)} loading={m.conflicts.isPending}>
                Kontroller konflikter
              </Button>
            </div>
            <ul className="ek-list-reset ek-stack" data-gap="3">
              {items.map((c) => (
                <li key={c.id} className="ek-card" style={{ padding: "1rem" }}>
                  <div className="ek-stack" data-gap="2">
                    <div className="ek-cluster" data-justify="between" data-align="start">
                      <Checkbox
                        label={<span className="ek-strong">{c.title}</span>}
                        hint={`${c.kind_label}${c.target.title ? ` · ${c.target.title}` : ""}`}
                        checked={selected.includes(c.id)}
                        onChange={(e) => setSelected((cur) => (e.target.checked ? [...cur, c.id] : cur.filter((x) => x !== c.id)))}
                      />
                      <Badge tone={STATUS[c.status].tone}>{STATUS[c.status].label}</Badge>
                    </div>
                    <div className="ek-cluster" data-gap="2">
                      <Badge tone={RISK[c.risk].tone}>{RISK[c.risk].label}</Badge>
                      <Badge>{UNDO[c.undo_capability]}</Badge>
                      {c.conflict_status === "ok" ? <Badge tone="success">Ingen konflikt</Badge> : null}
                      {c.conflict_status === "conflict" ? <Badge tone="warning">Konflikt</Badge> : null}
                      {c.ai_generated ? <Badge tone="violet">KI-forslag – må vurderes</Badge> : null}
                      {c.requires_confirmation ? <Badge tone="danger">Krever bekreftelse</Badge> : null}
                    </div>
                    {c.error ? <p className="ek-small ek-error">{c.error}</p> : null}
                    <Disclosure summary="Begrunnelse og angring">
                      <p className="ek-small" style={{ whiteSpace: "pre-line" }}>{c.rationale}</p>
                      <p className="ek-small ek-muted">{c.undo_note}</p>
                      {c.target.url ? (
                        <p className="ek-small">
                          <ExternalLink href={c.target.url}>Åpne i Canvas</ExternalLink>
                        </p>
                      ) : null}
                    </Disclosure>
                    <div className="ek-cluster" data-gap="2">
                      <Button size="sm" onClick={() => setPreview(c)}>
                        Forhåndsvis<span className="ek-visually-hidden">: {c.title}</span>
                      </Button>
                      {c.status === "staged" || c.status === "failed" || c.status === "conflict" ? (
                        <Button size="sm" onClick={() => m.approve.mutate([c.id])}>
                          Godkjenn<span className="ek-visually-hidden">: {c.title}</span>
                        </Button>
                      ) : null}
                      <Button size="sm" variant="primary" disabled={Boolean(running) || c.status === "conflict"} onClick={() => startApply([c.id])}>
                        Gjennomfør<span className="ek-visually-hidden">: {c.title}</span>
                      </Button>
                      {c.editable && c.status !== "applied" ? (
                        <Button size="sm" aria-expanded={editing === c.id} onClick={() => setEditing(editing === c.id ? null : c.id)}>
                          Rediger<span className="ek-visually-hidden">: {c.title}</span>
                        </Button>
                      ) : null}
                      <Button size="sm" variant="ghost" onClick={() => m.discard.mutate(c.id)}>
                        Fjern<span className="ek-visually-hidden">: {c.title}</span>
                      </Button>
                    </div>
                    {editing === c.id ? (
                      <EditChange change={c} saving={m.edit.isPending}
                        onSave={(proposed) => m.edit.mutate({ id: c.id, proposed }, { onSuccess: () => setEditing(null) })} />
                    ) : null}
                    {editing === c.id && m.edit.error ? <Alert tone="danger" role="alert">{(m.edit.error as Error).message}</Alert> : null}
                  </div>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </div>

      <Dialog open={preview !== null} onClose={() => setPreview(null)} size="xl" title={preview?.title ?? ""}
        description={preview?.kind_label}>
        {preview ? <ChangePreview change={preview} /> : null}
      </Dialog>

      <ConfirmDialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm && confirmChecked) {
            runApply(confirm.ids, true);
            setConfirm(null);
          }
        }}
        title="Bekreft endringer med høy risiko"
        confirmLabel="Gjennomfør"
        confirmDisabled={!confirmChecked}
        danger
      >
        <p>
          En eller flere endringer har høy risiko (for eksempel å erstatte forsiden). EmneKlar tar sikkerhetskopi først, men
          les forhåndsvisningen nøye.
        </p>
        <Checkbox
          label="Jeg har forhåndsvist og kontrollert endringene"
          checked={confirmChecked}
          onChange={(e) => setConfirmChecked(e.target.checked)}
        />
      </ConfirmDialog>
    </Dialog>
  );
}

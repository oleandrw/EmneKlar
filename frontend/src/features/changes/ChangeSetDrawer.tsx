// «Endringskø»: one queue for every feature and course. Approve (one, several or all), then «Publiser til Canvas»:
// a short confirmation of which courses and how many changes, progress while publishing, and the result per change
// with a way forward for each problem (retry, rebuild after a conflict, move a Blueprint-locked fix, sync).
import { CloudUpload, RefreshCw, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { Job } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { RISK, UNDO } from "../../core/labels";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  ConfirmDialog,
  Dialog,
  DiffView,
  Disclosure,
  EmptyState,
  ExternalLink,
  ProgressBar,
  Spinner,
  TextField,
  useToast,
  type Tone,
} from "../../design-system";
import { FINAL_STATUSES, useJob } from "../analysis/useJob";
import {
  useBlueprintMovePlan,
  useChangeMutations,
  useChanges,
  useSyncStatus,
  type Change,
  type PublishResult,
} from "./api";
import { ChangePreview } from "./ChangePreview";

const STATUS: Record<Change["status"], { label: string; tone: Tone }> = {
  staged: { label: "Venter på godkjenning", tone: "info" },
  approved: { label: "Godkjent – klar til publisering", tone: "success" },
  applying: { label: "Publiseres …", tone: "info" },
  applied: { label: "Publisert", tone: "success" },
  failed: { label: "Feilet", tone: "danger" },
  conflict: { label: "Konflikt", tone: "warning" },
  discarded: { label: "Fjernet", tone: "neutral" },
  undone: { label: "Angret", tone: "neutral" },
};

const RESULT: Record<string, { label: string; tone: Tone }> = {
  applied: { label: "Publisert", tone: "success" },
  conflict: { label: "Konflikt – ikke sendt", tone: "warning" },
  failed: { label: "Feilet", tone: "danger" },
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

function SyncStatusLine({ courseId, migrationId }: { courseId: string; migrationId: string }) {
  const status = useSyncStatus(courseId, migrationId);
  if (!status.data) return <Spinner label="Henter status for synkroniseringen …" />;
  return (
    <Badge tone={status.data.failed ? "danger" : status.data.finished ? "success" : "info"} dot>
      Synkronisering: {status.data.label}
    </Badge>
  );
}

/** Move a fix that Canvas refused (locked by Blueprint) to the Blueprint course, then sync. */
function BlueprintMoveDialog({ change, onClose }: { change: Change | null; onClose: () => void }) {
  const plan = useBlueprintMovePlan(change?.id ?? null);
  const m = useChangeMutations();
  const toast = useToast();
  return (
    <Dialog open={change !== null} onClose={onClose} size="lg" title="Rett i Blueprint-emnet"
      description="Innholdet er låst av Blueprint-emnet, så rettingen må gjøres der og synkroniseres til de tilknyttede emnene."
      footer={
        <>
          <Button onClick={onClose}>Avbryt</Button>
          <Button variant="primary" disabled={!plan.data} loading={m.moveToBlueprint.isPending}
            onClick={() => change && m.moveToBlueprint.mutate(change.id, {
              onSuccess: () => {
                toast.show({ tone: "success", title: "Rettingen er flyttet til Blueprint-emnet",
                  body: "Rettingen og en synkronisering er godkjent og klare. Publiser dem når du vil – synkroniseringen bekreftes ekstra." });
                onClose();
              },
            })}>
            Flytt rettingen og legg synkronisering i kø
          </Button>
        </>
      }>
      {plan.isPending ? <Spinner label="Finner innholdet i Blueprint-emnet …" /> : null}
      {plan.error ? <Alert tone="warning" role="alert" title="Kan ikke flyttes automatisk">{(plan.error as Error).message}</Alert> : null}
      {plan.data ? (
        <div className="ek-stack">
          <p>
            Rettingen gjøres i Blueprint-emnet <span className="ek-strong">«{plan.data.parent.name ?? plan.data.parent.id}»</span> og
            når {plan.data.associated_course_count === 1 ? "det tilknyttede emnet"
              : `${plan.data.associated_course_count ?? "de"} tilknyttede emnene`} når Blueprint-emnet synkroniseres.
          </p>
          {plan.data.associated_courses.length ? (
            <p className="ek-small ek-muted">Tilknyttede emner: {plan.data.associated_courses.map((c) => c.name ?? c.id).join(", ")}</p>
          ) : null}
          <p className="ek-small">{plan.data.note}</p>
          <DiffView before={plan.data.before_display} after={plan.data.after_display} beforeTitle="Nå i Blueprint-emnet"
            afterTitle="Etter rettingen" />
        </div>
      ) : null}
      {m.moveToBlueprint.error ? <Alert tone="danger" role="alert">{(m.moveToBlueprint.error as Error).message}</Alert> : null}
    </Dialog>
  );
}

export function ChangeSetDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const { courseId } = useCurrentCourse();
  const changes = useChanges(open);
  const m = useChangeMutations();
  const [preview, setPreview] = useState<Change | null>(null);
  const [moving, setMoving] = useState<Change | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<number[] | null>(null);
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId ?? changes.data?.publishing_job?.id ?? null);

  const items = useMemo(() => changes.data?.items ?? [], [changes.data]);
  const byId = useMemo(() => new Map(items.map((c) => [c.id, c])), [items]);
  useEffect(() => {
    if (job.data && FINAL_STATUSES.has(job.data.status)) m.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data?.status]);

  const staged = items.filter((c) => c.status === "staged" || c.status === "failed").map((c) => c.id);
  const approved = items.filter((c) => c.status === "approved");
  const running = Boolean(job.data && !FINAL_STATUSES.has(job.data.status));
  const results = (job.data?.result as { results?: PublishResult[]; course_names?: Record<string, string> } | undefined)?.results;
  const courseNames = (job.data?.result as { course_names?: Record<string, string> } | undefined)?.course_names ?? {};
  const courses = useMemo(() => {
    const list = [...(changes.data?.courses ?? [])];
    return list.sort((a, b) => (a.course_id === courseId ? -1 : b.course_id === courseId ? 1 : 0));
  }, [changes.data, courseId]);

  const publish = (ids: number[]) => {
    setConfirmChecked(false);
    setConfirm(ids);
  };
  const runPublish = (ids: number[], confirmed: boolean) =>
    m.apply.mutate(
      { ids, confirm: confirmed },
      {
        onSuccess: (created: Job) => setJobId(created.id),
        onError: (error) => toast.show({ tone: "danger", title: "Kunne ikke starte publiseringen", body: (error as Error).message }),
      },
    );
  const retry = (id: number) => m.approve.mutate([id], { onSuccess: () => runPublish([id], byId.get(id)?.requires_confirmation ?? false) });

  const confirmIds = confirm ?? [];
  const confirmChanges = confirmIds.map((id) => byId.get(id)).filter(Boolean) as Change[];
  const confirmCourses = Object.entries(confirmChanges.reduce<Record<string, number>>((acc, c) => {
    acc[c.course_name ?? c.course_id] = (acc[c.course_name ?? c.course_id] ?? 0) + 1;
    return acc;
  }, {}));
  const highRisk = confirmChanges.filter((c) => c.requires_confirmation);
  // Blueprint courses that got changes in this publish – unless they were synced in the same publish.
  const synced = new Set(results?.filter((r) => r.kind === "blueprint.sync" && r.status === "applied").map((r) => r.course_id) ?? []);
  const blueprintCourses = new Set(results?.filter((r) => r.blueprint?.sync_needed && !synced.has(r.course_id))
    .map((r) => r.course_id) ?? []);
  const summary = changes.data?.summary;

  return (
    <Dialog open={open} onClose={onClose} variant="drawer" size="lg" title="Endringskø"
      description="Godkjente forslag fra alle verktøy og emner samles her. Ingenting sendes til Canvas før du velger «Publiser til Canvas» – innholdet sikkerhetskopieres og endringen logges først.">
      <div className="ek-stack" data-gap="6">
        {changes.isPending ? <Spinner label="Henter endringer …" /> : null}
        {changes.error ? <Alert tone="danger">{(changes.error as Error).message}</Alert> : null}

        {running && job.data ? (
          <div className="ek-stack" data-gap="2" role="status">
            <p className="ek-strong">Publiserer til Canvas …</p>
            <ProgressBar label="Publisering" value={job.data.progress.total ? job.data.progress.done : null}
              max={Math.max(1, job.data.progress.total)}
              valueText={`${job.data.progress.done} av ${job.data.progress.total} endringer`} />
            <p className="ek-xs ek-muted">
              {job.data.progress.current_item ? `Nå: ${job.data.progress.current_item}. ` : ""}
              Endringer avbrytes aldri midt i en skriving.
            </p>
          </div>
        ) : null}

        {results && job.data && FINAL_STATUSES.has(job.data.status) ? (
          <Alert tone={results.every((r) => r.status === "applied") ? "success" : "warning"} title="Resultat av publiseringen" role="status">
            <ul className="ek-publish-list">
              {results.map((r) => {
                const label = RESULT[r.status] ?? { label: r.status, tone: "neutral" as Tone };
                const migration = r.status === "applied" && r.migration_id ? String(r.migration_id) : "";
                return (
                  <li key={r.change_id}>
                    <Badge tone={label.tone} dot>{label.label}</Badge>
                    <span>{r.title}</span>
                    {courseNames[r.course_id] ? <span className="ek-xs ek-muted">({courseNames[r.course_id]})</span> : null}
                    {r.message && r.status !== "applied" ? <span className="ek-small">– {r.message}</span> : null}
                    {r.message && r.status === "applied" && r.message.includes("allerede") ? <span className="ek-small ek-muted">– {r.message}</span> : null}
                    {migration ? <SyncStatusLine courseId={r.course_id} migrationId={migration} /> : null}
                  </li>
                );
              })}
            </ul>
            {blueprintCourses.size ? (
              <div className="ek-stack" data-gap="2">
                <p className="ek-small">
                  Endringer i Blueprint-emner når de tilknyttede emnene først når Blueprint-emnet synkroniseres.
                </p>
                <div className="ek-cluster">
                  {[...blueprintCourses].map((course) => (
                    <Button key={course} size="sm" loading={m.stageSync.isPending} onClick={() => m.stageSync.mutate(course, {
                      onSuccess: () => toast.show({ tone: "success", title: "Synkronisering lagt i endringskøen", body: "Den må bekreftes når du publiserer." }),
                    })}>
                      Legg synkronisering av «{courseNames[course] ?? course}» i kø
                    </Button>
                  ))}
                </div>
              </div>
            ) : null}
          </Alert>
        ) : null}

        {changes.data && items.length === 0 ? (
          <EmptyState title="Ingen endringer i kø" headingLevel={3}>
            Forslag du godkjenner fra funn og verktøy, vises her. Ingenting sendes til Canvas før du publiserer.
          </EmptyState>
        ) : null}

        {changes.data && items.length > 0 ? (
          <>
            <div className="ek-stack" data-gap="3">
              <p className="ek-strong" aria-live="polite">
                {approved.length} klar{approved.length === 1 ? "" : "e"} til publisering · {staged.length} venter på godkjenning
                {summary?.problems ? ` · ${summary.problems} må ses på` : ""} · {courses.length} {courses.length === 1 ? "emne" : "emner"}
              </p>
              <ul className="ek-cluster ek-list-reset" aria-label="Endringer per område">
                {changes.data.groups.map((g) => (
                  <li key={g.domain}><Badge tone="info">{g.count} {g.label}</Badge></li>
                ))}
              </ul>
              <div className="ek-cluster">
                <Button variant="primary" icon={<CloudUpload aria-hidden="true" />} disabled={!approved.length || running}
                  onClick={() => publish(approved.map((c) => c.id))}>
                  Publiser til Canvas ({approved.length})
                </Button>
                <Button disabled={!staged.length} loading={m.approve.isPending} onClick={() => m.approve.mutate(staged)}>
                  Godkjenn alle ({staged.length})
                </Button>
                <Button variant="ghost" disabled={!items.length} loading={m.conflicts.isPending}
                  onClick={() => m.conflicts.mutate(items.filter((c) => c.status !== "applying").map((c) => c.id))}>
                  Kontroller mot Canvas
                </Button>
              </div>
            </div>

            {courses.map((course) => (
              <section key={course.course_id} className="ek-stack" data-gap="3" aria-labelledby={`emne-${course.course_id}`}>
                <h3 id={`emne-${course.course_id}`}>
                  {course.name ?? `Emne ${course.course_id}`}{" "}
                  <span className="ek-small ek-muted">({course.count} {course.count === 1 ? "endring" : "endringer"}, {course.approved} godkjent)</span>
                </h3>
                <ul className="ek-list-reset ek-stack" data-gap="3">
                  {items.filter((c) => c.course_id === course.course_id).map((c) => (
                    <li key={c.id} className="ek-card ek-card--compact">
                      <div className="ek-stack" data-gap="2">
                        <div className="ek-cluster" data-justify="between" data-align="start">
                          <div className="ek-stack" data-gap="1">
                            <span className="ek-strong">{c.title}</span>
                            <span className="ek-xs ek-muted">
                              {c.kind_label}{c.target.module ? ` · ${c.target.module}` : ""}{c.fix_count > 1 ? ` · ${c.fix_count} rettinger` : ""}
                            </span>
                          </div>
                          <Badge tone={STATUS[c.status].tone} dot>{STATUS[c.status].label}</Badge>
                        </div>
                        <div className="ek-cluster" data-gap="2">
                          <Badge tone={RISK[c.risk].tone}>{RISK[c.risk].label}</Badge>
                          {c.conflict_status === "ok" ? <Badge tone="success">Ingen konflikt</Badge> : null}
                          {c.ai_generated ? <Badge tone="violet">KI-forslag – må vurderes</Badge> : null}
                          {c.requires_confirmation ? <Badge tone="danger">Krever bekreftelse</Badge> : null}
                          {c.target.moved_from ? <Badge tone="info">Flyttet fra tilknyttet emne</Badge> : null}
                        </div>
                        {c.error ? <p className="ek-small ek-error" role="alert">{c.error}</p> : null}
                        <div className="ek-cluster" data-gap="2">
                          <Button size="sm" onClick={() => setPreview(c)}>
                            Forhåndsvis<span className="ek-visually-hidden">: {c.title}</span>
                          </Button>
                          {c.status === "staged" ? (
                            <Button size="sm" variant="primary" onClick={() => m.approve.mutate([c.id])}>
                              Godkjenn<span className="ek-visually-hidden">: {c.title}</span>
                            </Button>
                          ) : null}
                          {c.status === "approved" ? (
                            <Button size="sm" variant="ghost" icon={<Undo2 aria-hidden="true" />} onClick={() => m.unapprove.mutate([c.id])}>
                              Angre godkjenning<span className="ek-visually-hidden">: {c.title}</span>
                            </Button>
                          ) : null}
                          {c.status === "failed" && c.result?.error_category !== "blueprint" ? (
                            <Button size="sm" icon={<RefreshCw aria-hidden="true" />} disabled={running} onClick={() => retry(c.id)}>
                              Prøv igjen<span className="ek-visually-hidden">: {c.title}</span>
                            </Button>
                          ) : null}
                          {c.status === "failed" && c.result?.error_category === "blueprint" ? (
                            <Button size="sm" variant="primary" onClick={() => setMoving(c)}>
                              Rett i Blueprint-emnet<span className="ek-visually-hidden">: {c.title}</span>
                            </Button>
                          ) : null}
                          {c.status === "conflict" && c.rebuildable ? (
                            <Button size="sm" loading={m.rebuild.isPending && m.rebuild.variables === c.id} onClick={() => m.rebuild.mutate(c.id, {
                              onSuccess: () => toast.show({ tone: "success", title: "Forslaget er laget på nytt", body: "Det bygger nå på innholdet slik det er i Canvas. Se over og godkjenn." }),
                              onError: (error) => toast.show({ tone: "danger", title: "Kunne ikke lage forslaget på nytt", body: (error as Error).message }),
                            })}>
                              Lag forslaget på nytt<span className="ek-visually-hidden">: {c.title}</span>
                            </Button>
                          ) : null}
                          {c.editable && c.status !== "applied" ? (
                            <Button size="sm" aria-expanded={editing === c.id} onClick={() => setEditing(editing === c.id ? null : c.id)}>
                              Rediger<span className="ek-visually-hidden">: {c.title}</span>
                            </Button>
                          ) : null}
                          {c.status !== "applying" ? (
                            <Button size="sm" variant="ghost" onClick={() => m.discard.mutate(c.id)}>
                              Fjern<span className="ek-visually-hidden">: {c.title}</span>
                            </Button>
                          ) : null}
                        </div>
                        {editing === c.id ? (
                          <EditChange change={c} saving={m.edit.isPending}
                            onSave={(proposed) => m.edit.mutate({ id: c.id, proposed }, { onSuccess: () => setEditing(null) })} />
                        ) : null}
                        {editing === c.id && m.edit.error ? <Alert tone="danger" role="alert">{(m.edit.error as Error).message}</Alert> : null}
                        <Disclosure summary="Begrunnelse og angring">
                          <p className="ek-small ek-pre-line">{c.rationale}</p>
                          <p className="ek-small ek-muted">{UNDO[c.undo_capability]}. {c.undo_note}</p>
                          {c.target.url ? <p className="ek-small"><ExternalLink href={c.target.url}>Åpne i Canvas</ExternalLink></p> : null}
                        </Disclosure>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </>
        ) : null}
      </div>

      <Dialog open={preview !== null} onClose={() => setPreview(null)} size="xl" title={preview?.title ?? ""}
        description={preview?.kind_label}>
        {preview ? <ChangePreview change={preview} /> : null}
      </Dialog>

      <BlueprintMoveDialog change={moving} onClose={() => setMoving(null)} />

      <ConfirmDialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm && (!highRisk.length || confirmChecked)) {
            runPublish(confirm, highRisk.length > 0);
            setConfirm(null);
          }
        }}
        title="Publiser til Canvas"
        confirmLabel={`Publiser ${confirmIds.length} ${confirmIds.length === 1 ? "endring" : "endringer"}`}
        confirmDisabled={highRisk.length > 0 && !confirmChecked}
        danger={highRisk.length > 0}
      >
        <p>Dette sendes til Canvas nå:</p>
        <ul>
          {confirmCourses.map(([name, count]) => (
            <li key={name}><span className="ek-strong">{name}</span>: {count} {count === 1 ? "endring" : "endringer"}</li>
          ))}
        </ul>
        <p className="ek-muted">
          Innholdet kontrolleres mot Canvas og sikkerhetskopieres før hver endring. Er noe endret i Canvas etter forslaget
          ble laget, stoppes endringen i stedet for å overskrive nyere arbeid. Flere endringer på samme side publiseres etter
          hverandre, så ingen retting overskriver en annen.
        </p>
        {highRisk.length ? (
          <>
            <Alert tone="warning" title={`${highRisk.length} ${highRisk.length === 1 ? "endring har" : "endringer har"} høy risiko`}>
              {highRisk.map((c) => c.title).join(", ")}
            </Alert>
            <Checkbox label="Jeg har forhåndsvist og kontrollert endringene med høy risiko" checked={confirmChecked}
              onChange={(e) => setConfirmChecked(e.target.checked)} />
          </>
        ) : null}
      </ConfirmDialog>
    </Dialog>
  );
}

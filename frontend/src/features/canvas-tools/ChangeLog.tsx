// «Sikkerhetskopier og endringslogg»: every change EmneKlar has published to Canvas, with safe undo where possible.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Undo2 } from "lucide-react";
import { useState } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime } from "../../core/format";
import { OBJECT_TYPE } from "../../core/labels";
import { ACTION, type LogAction } from "../changes/history";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DiffView,
  Disclosure,
  EmptyState,
  KeyValue,
  PageHeader,
  Spinner,
  useToast,
} from "../../design-system";

export interface LogEntry {
  id: number;
  timestamp: string | null;
  change_id: number | null;
  kind: string;
  object_type: string | null;
  object_id: string | null;
  object_title: string | null;
  action: LogAction;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  api_result: { sent?: boolean; message?: string; error?: string } | null;
  user_action: string | null;
  backup_id: number | null;
  undo_of: number | null;
  undoable: boolean;
  undone_by: number | null;
  /** What was changed, from what was recorded with the change («Lenketekst oppdatert»); null when not recorded. */
  summary?: string | null;
}

interface BackupInfo {
  id: number;
  created_at: string;
  object_type: string;
  object_id: string;
  title: string;
  size: number;
}

export const CHANGE_LOG_TITLE = "Sikkerhetskopier og endringslogg";
const HTML_KEYS = ["body", "description", "message", "syllabus_body", "question_text"];

function StateView({ before, after }: { before: Record<string, unknown> | null; after: Record<string, unknown> | null }) {
  const htmlKey = HTML_KEYS.find((k) => typeof before?.[k] === "string" || typeof after?.[k] === "string");
  if (htmlKey) {
    return <DiffView before={String(before?.[htmlKey] ?? "")} after={String(after?.[htmlKey] ?? "")} />;
  }
  const keys = Array.from(new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])).filter((k) => !k.startsWith("_"));
  const show = (v: unknown) => (v === null || v === undefined ? "–" : typeof v === "object" ? JSON.stringify(v) : String(v));
  return <KeyValue items={keys.map((k) => [k, `${show(before?.[k])} → ${show(after?.[k])}`])} />;
}

function download(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function ChangeLog() {
  const { courseId } = useCurrentCourse();
  const toast = useToast();
  const client = useQueryClient();
  const [undoing, setUndoing] = useState<LogEntry | null>(null);
  const log = useQuery({
    queryKey: ["changelog", courseId],
    queryFn: () => api.get<{ items: LogEntry[]; total: number }>(`/api/changelog?course_id=${courseId}&limit=100`),
    enabled: Boolean(courseId),
  });
  const backups = useQuery({
    queryKey: ["backups", courseId],
    queryFn: () => api.get<{ items: BackupInfo[] }>(`/api/backups?course_id=${courseId}`),
    enabled: Boolean(courseId),
  });
  const undo = useMutation({
    mutationFn: (id: number) => api.post<{ status: string; message?: string }>(`/api/changelog/${id}/undo`),
    onSuccess: (result) => {
      setUndoing(null);
      void client.invalidateQueries({ queryKey: ["changelog"] });
      void client.invalidateQueries({ queryKey: ["backups"] });
      void client.invalidateQueries({ queryKey: ["findings"] });
      toast.show({ tone: "success", title: result.message ?? "Endringen er angret" });
    },
  });
  const fetchBackup = useMutation({
    mutationFn: (id: number) => api.get<Record<string, unknown>>(`/api/backups/${id}`),
    onSuccess: (data, id) => download(`emneklar-sikkerhetskopi-${id}.json`, data),
  });

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;

  return (
    <>
      <PageHeader title={CHANGE_LOG_TITLE}
        description="Alle endringer EmneKlar har publisert til Canvas i emnet. Innholdet sikkerhetskopieres før hver endring." />
      <div className="ek-stack" data-gap="6">
        <Alert tone="info" title="Om angring">
          En endring kan angres når Canvas-API-et gjør det mulig og innholdet ikke er endret av andre etterpå. EmneKlar
          sjekker dette før angring og overskriver aldri nyere arbeid. Ikke alt kan angres automatisk.
        </Alert>
        {log.isPending ? <Spinner label="Henter endringsloggen …" /> : null}
        {log.error ? <Alert tone="danger" role="alert">{(log.error as Error).message}</Alert> : null}
        {log.data ? (
          log.data.items.length === 0 ? (
            <EmptyState title="Ingen endringer ennå" headingLevel={2}>Endringer du gjennomfører fra endringskøen, vises her.</EmptyState>
          ) : (
            <section className="ek-stack" aria-labelledby="logg">
              <h2 id="logg">Endringslogg ({log.data.total})</h2>
              <ol className="ek-list-reset ek-stack" data-gap="2">
                {log.data.items.map((entry) => (
                  <li key={entry.id} className="ek-card ek-card--compact">
                    <div className="ek-stack" data-gap="2">
                      <div className="ek-cluster" data-justify="between">
                        <div className="ek-cluster" data-gap="2">
                          <Badge tone={ACTION[entry.action]?.tone ?? "neutral"}>{ACTION[entry.action]?.label ?? entry.action}</Badge>
                          {entry.undone_by ? <Badge>Senere angret</Badge> : null}
                          <span className="ek-xs ek-muted">{formatDateTime(entry.timestamp)}</span>
                        </div>
                        {entry.undoable && entry.action === "apply" ? (
                          <Button size="sm" icon={<Undo2 aria-hidden="true" />} onClick={() => setUndoing(entry)}>
                            Angre<span className="ek-visually-hidden">: {entry.object_title}</span>
                          </Button>
                        ) : null}
                      </div>
                      <p className="ek-strong">
                        {OBJECT_TYPE[entry.object_type ?? ""] ?? entry.object_type}: {entry.object_title ?? entry.object_id}
                      </p>
                      {entry.summary ? <p>{entry.summary}</p> : null}
                      {entry.reason ? <p className="ek-small">{entry.reason}</p> : null}
                      {entry.api_result?.message || entry.api_result?.error ? (
                        <p className="ek-xs ek-muted">Canvas: {entry.api_result.error ?? entry.api_result.message}</p>
                      ) : null}
                      <Disclosure summary="Før og etter">
                        <StateView before={entry.before} after={entry.after} />
                      </Disclosure>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          )
        ) : null}

        <Card title="Sikkerhetskopier" headingLevel={2}>
          <p className="ek-small ek-muted">
            Tatt automatisk før hver endring og lagret lokalt på denne maskinen. Du kan laste dem ned som JSON.
          </p>
          {backups.data?.items.length ? (
            <ul className="ek-list-reset ek-divider-list ek-mt-4">
              {backups.data.items.map((b) => (
                <li key={b.id} className="ek-row">
                  <div className="ek-row__main">
                    <span>{OBJECT_TYPE[b.object_type] ?? b.object_type}: {b.title}</span>
                    <span className="ek-xs ek-muted">{formatDateTime(b.created_at)}</span>
                  </div>
                  <Button size="sm" icon={<Download aria-hidden="true" />} onClick={() => fetchBackup.mutate(b.id)}
                    loading={fetchBackup.isPending && fetchBackup.variables === b.id}>
                    Last ned<span className="ek-visually-hidden">: {b.title}</span>
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="ek-small ek-mt-4">Ingen sikkerhetskopier ennå.</p>
          )}
          {fetchBackup.error ? <Alert tone="danger" role="alert">{(fetchBackup.error as Error).message}</Alert> : null}
        </Card>
      </div>
      <ConfirmDialog
        open={undoing !== null}
        onClose={() => setUndoing(null)}
        onConfirm={() => undoing && undo.mutate(undoing.id)}
        title="Angre endringen?"
        confirmLabel="Angre endringen"
        loading={undo.isPending}
      >
        <p>EmneKlar kontrollerer først at innholdet i Canvas ikke er endret etter endringen. Er det endret, angres ingenting.</p>
        {undo.error ? <Alert tone="danger" role="alert">{(undo.error as Error).message}</Alert> : null}
      </ConfirmDialog>
    </>
  );
}

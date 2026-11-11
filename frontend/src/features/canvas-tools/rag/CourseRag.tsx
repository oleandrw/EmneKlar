// Canvas-verktøy → Emnets kunnskapsbase (internally Emne-RAG, course_rag): a local knowledge base of the course with cited answers.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, Download, Gauge, Hammer, MessageSquareText, RefreshCw, Settings2, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../../../core/api/client";
import { useCurrentCourse } from "../../../core/course";
import { formatDateTime, formatNumber } from "../../../core/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  Disclosure,
  EmptyState,
  KeyFigure,
  KeyFigureList,
  PageHeader,
  Spinner,
  Tabs,
  useToast,
  type Column,
  type Tone,
} from "../../../design-system";
import { JobRunner } from "../../analysis/JobRunner";
import { DEFAULT_OPTIONS, STATUS_LABEL, useRagStatus, type RagStatus, type SkippedItem } from "./api";
import { AskPanel } from "./AskPanel";
import { BuildPanel } from "./BuildPanel";
import { ExportPanel } from "./ExportPanel";
import { QualityPanel } from "./QualityPanel";
import { SettingsPanel } from "./SettingsPanel";

type TabId = "bygg" | "spor" | "kvalitet" | "eksport" | "innstillinger";

const STATUS_TONE: Record<string, Tone> = { ready: "success", partial: "warning", building: "info", failed: "danger",
  empty: "neutral" };

function SkippedTable({ items }: { items: SkippedItem[] }) {
  const columns: Column<SkippedItem>[] = [
    { key: "title", header: "Element", rowHeader: true, cell: (s) => s.url
      ? <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> : s.title },
    { key: "kind", header: "Type", cell: (s) => s.kind_label },
    { key: "reason", header: "Hvorfor", cell: (s) => (
      <span className="ek-stack" data-gap="1">
        {s.failed ? <Badge tone="danger">Feilet</Badge> : null}
        {s.waiting ? <Badge tone="info">Prøves igjen ved neste oppdatering</Badge> : null}
        <span>{s.reason}</span>
      </span>
    ) },
  ];
  return <DataTable caption="Elementer som ikke er med i kunnskapsbasen" captionHidden columns={columns} rows={items}
    rowKey={(s) => s.key + s.reason} empty="Ingen elementer ble hoppet over." />;
}

function IndexCard({ status, courseId }: { status: RagStatus; courseId: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [updateJob, setUpdateJob] = useState<string | null>(null);
  const update = useMutation({
    mutationFn: () => api.post<{ id: string }>(`/api/courses/${courseId}/rag/build`, {
      ...DEFAULT_OPTIONS, ...(status.index?.options ?? {}), mode: "update" }),
    onSuccess: (job) => setUpdateJob(job.id),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/api/courses/${courseId}/rag`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["rag", courseId] });
      toast.show({ tone: "success", title: "Kunnskapsbasen er slettet", body: "Ingenting er endret i Canvas." });
    },
  });
  const index = status.index;
  const stats = status.stats;
  if (!index || !stats) return null;  // the page header says «Ingen kunnskapsbase opprettet ennå»
  const types = stats.chunk_types;
  return (
    <Card title="Status" headingLevel={2}
      actions={<Badge tone={STATUS_TONE[index.status] ?? "neutral"}>{STATUS_LABEL[index.status] ?? index.status}</Badge>}>
      <div className="ek-stack" data-gap="4">
        <p className="ek-small">
          {index.built_at ? `Sist bygget eller oppdatert: ${formatDateTime(index.built_at)}.` : "Ikke ferdig bygget ennå."}{" "}
          Søk: {status.index_embedding ? `${index.embedding?.label ?? "ukjent modell"} og nøkkelord` : "bare nøkkelord (BM25)"}.
          {"health" in (index.evaluation ?? {}) ? ` Helsescore for søket: ${(index.evaluation as { health: number }).health} av 100.` : ""}
        </p>
        {index.status === "partial" ? (
          <Alert tone="warning" title="Kunnskapsbasen er ufullstendig">
            Byggingen ble avbrutt eller stoppet. Det som er ferdig, kan brukes. Velg «Oppdater kunnskapsbasen» for å fortsette –
            ferdige elementer hoppes over.
          </Alert>
        ) : null}
        {status.model_mismatch ? (
          <Alert tone="warning" title="Annen søkemodell valgt">
            Kunnskapsbasen er laget med en annen embedding-modell enn den som er valgt nå. Søket bruker bare nøkkelord
            til du bygger den på nytt.
          </Alert>
        ) : null}
        <KeyFigureList label="Innhold i kunnskapsbasen">
          <KeyFigure icon={<BookOpenText />} tone="info" value={stats.chunks} label="utdrag"
            description={`${formatNumber(Object.values(stats.items).reduce((a, b) => a + b, 0))} elementer`} />
          <KeyFigure icon={<BookOpenText />} tone="violet" value={types.table ?? 0} label="tabeller" />
          <KeyFigure icon={<BookOpenText />} tone="teal" value={types.slide ?? 0} label="lysbilder" />
          <KeyFigure icon={<BookOpenText />} tone="orange" value={(types.transcript ?? 0) + (types.image ?? 0)}
            label="video- og bildeutdrag" />
        </KeyFigureList>
        {index.skipped.length ? (
          <Disclosure summary={`Hoppet over: ${index.skipped.length} elementer`}>
            <SkippedTable items={index.skipped} />
          </Disclosure>
        ) : null}
        {index.limitations.length ? (
          <Alert tone="warning" title="Begrensninger">
            <ul>{index.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </Alert>
        ) : null}
        {updateJob ? (
          <JobRunner jobId={updateJob} onDone={(job) => {
            setUpdateJob(null);
            void client.invalidateQueries({ queryKey: ["rag", courseId] });
            if (job.status === "completed") toast.show({ tone: "success", title: "Kunnskapsbasen er oppdatert" });
          }} />
        ) : null}
        <div className="ek-cluster">
          <Button variant="primary" icon={<RefreshCw aria-hidden="true" />} onClick={() => update.mutate()}
            loading={update.isPending} disabled={Boolean(status.busy_job || updateJob)}>
            Oppdater kunnskapsbasen
          </Button>
          <Button variant="danger" icon={<Trash2 aria-hidden="true" />} onClick={() => setConfirmDelete(true)}
            disabled={Boolean(status.busy_job || updateJob)}>
            Slett kunnskapsbasen
          </Button>
        </div>
        <p className="ek-xs ek-muted">
          «Oppdater kunnskapsbasen» bruker de samme valgene som sist og behandler bare nye og endrede elementer. Må
          noe lastes ned eller sendes til KI, går du via fanen «Kunnskapsbase», der du ser estimatet først.
        </p>
        {update.error ? <Alert tone="warning" role="alert">{(update.error as Error).message}</Alert> : null}
      </div>
      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} danger
        title="Slette kunnskapsbasen?" confirmLabel="Slett kunnskapsbasen" cancelLabel="Behold kunnskapsbasen"
        onConfirm={() => { setConfirmDelete(false); remove.mutate(); }}>
        <p>Kunnskapsbasen for emnet slettes fra denne maskinen. Ingenting endres i Canvas, og du kan opprette den på
          nytt.</p>
      </ConfirmDialog>
    </Card>
  );
}

export function CourseRag() {
  const { courseId } = useCurrentCourse();
  const status = useRagStatus(courseId);
  const [tab, setTab] = useState<TabId | null>(null);
  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  const ready = Boolean(status.data?.stats?.chunks);
  const current: TabId = tab ?? (ready ? "spor" : "bygg");
  return (
    <>
      <PageHeader title="Emnets kunnskapsbase"
        description="Samle tekst, dokumenter, bilder og video fra emnet på denne maskinen, og still spørsmål med klikkbare kilder."
        status={status.data && !status.data.index ? <Badge dot>Ingen kunnskapsbase opprettet ennå</Badge> : undefined} />
      <div className="ek-stack" data-gap="6">
        {status.isPending ? <Spinner label="Henter status for kunnskapsbasen …" /> : status.error ? (
          <Alert tone="danger" role="alert">{(status.error as Error).message}</Alert>
        ) : (
          <>
            {status.data.error ? <Alert tone="danger" role="alert">{status.data.error.message}</Alert> : null}
            <IndexCard status={status.data} courseId={courseId} />
            <Tabs<TabId> label="Emnets kunnskapsbase" selected={current} onSelect={setTab} tabs={[
              { id: "bygg", label: "Kunnskapsbase", icon: <Hammer aria-hidden="true" /> },
              { id: "spor", label: "Spør emnet", icon: <MessageSquareText aria-hidden="true" /> },
              { id: "kvalitet", label: "Kvalitet", icon: <Gauge aria-hidden="true" /> },
              { id: "eksport", label: "Eksport", icon: <Download aria-hidden="true" /> },
              { id: "innstillinger", label: "Innstillinger", icon: <Settings2 aria-hidden="true" /> },
            ]}>
              <div className="ek-stack ek-mt-6" data-gap="6">
                {current === "bygg" ? <BuildPanel courseId={courseId} status={status.data} /> : null}
                {current === "spor" ? <AskPanel courseId={courseId} status={status.data} /> : null}
                {current === "kvalitet" ? <QualityPanel courseId={courseId} status={status.data} /> : null}
                {current === "eksport" ? <ExportPanel courseId={courseId} status={status.data} /> : null}
                {current === "innstillinger" ? <SettingsPanel status={status.data} courseId={courseId} /> : null}
              </div>
            </Tabs>
          </>
        )}
      </div>
    </>
  );
}

// Canvas-verktøy → Emne-RAG: a local knowledge base of the course with cited answers.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, Hammer, MessageSquareText, Settings2, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../../../core/api/client";
import { useCurrentCourse } from "../../../core/course";
import { formatDateTime, formatNumber } from "../../../core/format";
import { HelpLink } from "../../../core/HelpLink";
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
import { BackToTools } from "../shared";
import { STATUS_LABEL, useRagStatus, type RagStatus, type SkippedItem } from "./api";
import { AskPanel } from "./AskPanel";
import { BuildPanel } from "./BuildPanel";
import { SettingsPanel } from "./SettingsPanel";

type TabId = "bygg" | "spor" | "innstillinger";

const STATUS_TONE: Record<string, Tone> = { ready: "success", partial: "warning", building: "info", failed: "danger",
  empty: "neutral" };

export function PrivacyNotice() {
  return (
    <Alert tone="info" title="Bare lærerens innhold">
      <p>
        Emne-RAG leser sider, oppgave- og quizbeskrivelser, emneplanen, diskusjonsinnlegg skrevet av lærere og filer
        lastet opp av lærere. Innleveringer, karakterer, meldinger, studentenes innlegg og svar i diskusjoner hentes
        aldri. Indeksen lagres bare på denne maskinen, og ingenting endres i Canvas.
      </p>
    </Alert>
  );
}

function SkippedTable({ items }: { items: SkippedItem[] }) {
  const columns: Column<SkippedItem>[] = [
    { key: "title", header: "Element", rowHeader: true, cell: (s) => s.url
      ? <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> : s.title },
    { key: "kind", header: "Type", cell: (s) => s.kind_label },
    { key: "reason", header: "Hvorfor", cell: (s) => (
      <span className="ek-stack" data-gap="1">
        {s.failed ? <Badge tone="danger">Feilet</Badge> : null}
        <span>{s.reason}</span>
      </span>
    ) },
  ];
  return <DataTable caption="Elementer som ikke er med i indeksen" captionHidden columns={columns} rows={items}
    rowKey={(s) => s.key + s.reason} empty="Ingen elementer ble hoppet over." />;
}

function IndexCard({ status, courseId }: { status: RagStatus; courseId: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.delete(`/api/courses/${courseId}/rag`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["rag", courseId] });
      toast.show({ tone: "success", title: "Indeksen er slettet", body: "Ingenting er endret i Canvas." });
    },
  });
  const index = status.index;
  const stats = status.stats;
  if (!index || !stats) {
    return (
      <Card title="Indeks" headingLevel={2}>
        <p className="ek-muted">Det finnes ingen indeks for emnet ennå. Velg innhold under «Bygg indeks».</p>
      </Card>
    );
  }
  const types = stats.chunk_types;
  return (
    <Card title="Indeks" headingLevel={2}
      actions={<Badge tone={STATUS_TONE[index.status] ?? "neutral"}>{STATUS_LABEL[index.status] ?? index.status}</Badge>}>
      <div className="ek-stack" data-gap="4">
        <p className="ek-small">
          {index.built_at ? `Sist bygget eller oppdatert: ${formatDateTime(index.built_at)}.` : "Ikke ferdig bygget ennå."}{" "}
          Søkemodell: {index.embedding?.label ?? "ukjent"}
          {status.index_embedding ? "" : " (bare nøkkelordsøk)"}.
        </p>
        {index.status === "partial" ? (
          <Alert tone="warning" title="Indeksen er ufullstendig">
            Byggingen ble avbrutt eller stoppet. Det som er ferdig, kan brukes. Velg «Oppdater indeks» for å fortsette –
            ferdige elementer hoppes over.
          </Alert>
        ) : null}
        {status.model_mismatch ? (
          <Alert tone="warning" title="Annen søkemodell valgt">
            Indeksen er laget med en annen embedding-modell enn den som er valgt nå. Søket bruker bare nøkkelord til du
            bygger indeksen på nytt.
          </Alert>
        ) : null}
        <KeyFigureList label="Innhold i indeksen">
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
        <div className="ek-cluster">
          <Button variant="danger" icon={<Trash2 aria-hidden="true" />} onClick={() => setConfirmDelete(true)}
            disabled={Boolean(status.busy_job)}>
            Slett indeks
          </Button>
        </div>
      </div>
      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} danger
        title="Slette indeksen?" confirmLabel="Slett indeksen" cancelLabel="Behold indeksen"
        onConfirm={() => { setConfirmDelete(false); remove.mutate(); }}>
        <p>Indeksen for emnet slettes fra denne maskinen. Ingenting endres i Canvas, og du kan bygge den på nytt.</p>
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
      <PageHeader title="Emne-RAG"
        description="Lag en lokal kunnskapsbase av emnet – tekst, dokumenter, bilder og video – og still spørsmål med klikkbare kilder."
        actions={<HelpLink topic="emne-rag" />} />
      <div className="ek-stack" data-gap="6">
        <BackToTools />
        <PrivacyNotice />
        {status.isPending ? <Spinner label="Henter status for indeksen …" /> : status.error ? (
          <Alert tone="danger" role="alert">{(status.error as Error).message}</Alert>
        ) : (
          <>
            {status.data.error ? <Alert tone="danger" role="alert">{status.data.error.message}</Alert> : null}
            <IndexCard status={status.data} courseId={courseId} />
            <Tabs<TabId> label="Emne-RAG" selected={current} onSelect={setTab} tabs={[
              { id: "bygg", label: ready ? "Oppdater indeks" : "Bygg indeks", icon: <Hammer aria-hidden="true" /> },
              { id: "spor", label: "Spør emnet", icon: <MessageSquareText aria-hidden="true" /> },
              { id: "innstillinger", label: "Innstillinger", icon: <Settings2 aria-hidden="true" /> },
            ]}>
              <div className="ek-stack ek-mt-6" data-gap="6">
                {current === "bygg" ? <BuildPanel courseId={courseId} status={status.data} /> : null}
                {current === "spor" ? <AskPanel courseId={courseId} status={status.data} /> : null}
                {current === "innstillinger" ? <SettingsPanel status={status.data} courseId={courseId} /> : null}
              </div>
            </Tabs>
          </>
        )}
        <p className="ek-small ek-muted ek-cluster" data-gap="2">
          <ShieldCheck aria-hidden="true" />
          <span>Embedding, rerangering og transkripsjon kjører lokalt. KI brukes bare når du velger det, og du ser hva
            som sendes først.</span>
        </p>
      </div>
    </>
  );
}

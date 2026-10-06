import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink as ExternalIcon, FileChartColumn, Trash } from "lucide-react";
import { useState } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime } from "../../core/format";
import { HelpLink } from "../../core/HelpLink";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  EmptyState,
  PageHeader,
  RadioGroup,
  Spinner,
  useToast,
  type Column,
} from "../../design-system";

interface ReportTypes {
  types: { value: string; label: string; analysed: boolean }[];
  formats: { value: "html" | "csv"; label: string }[];
}

interface Report {
  id: number;
  report_type: string;
  type_label: string;
  format: "html" | "csv";
  title: string;
  filename: string;
  size: number;
  created_at: string | null;
}

const TYPE_HINTS: Record<string, string> = {
  full: "Alle områdene samlet: universell utforming, innholdskvalitet, struktur og quiz.",
  accessibility: "Funn etter regelsett og valgt regulatorisk profil, med manuelle kontroller og begrensninger.",
  content_quality: "Lenker, medier og HTML-kode.",
  structure: "Forslag til moduler, rekkefølge og navngiving.",
  quiz: "Kvalitetssjekk av klassiske quizer, inkludert KI-vurderinger hvis de er kjørt.",
};

function formatSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} kB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function ReportsPage() {
  usePageTitle("Rapporter");
  const { courseId } = useCurrentCourse();
  const ui = useUi();
  const toast = useToast();
  const client = useQueryClient();
  const [type, setType] = useState("full");
  const [format, setFormat] = useState<"html" | "csv">("html");
  const [deleting, setDeleting] = useState<Report | null>(null);
  const types = useQuery({
    queryKey: ["report-types", courseId],
    queryFn: () => api.get<ReportTypes>(`/api/courses/${courseId}/reports/types`),
    enabled: Boolean(courseId),
  });
  const reports = useQuery({
    queryKey: ["reports", courseId],
    queryFn: () => api.get<{ items: Report[] }>(`/api/reports?course_id=${courseId}`),
    enabled: Boolean(courseId),
  });
  const create = useMutation({
    mutationFn: () => api.post<Report>(`/api/courses/${courseId}/reports`, { report_type: type, format }),
    onSuccess: (report) => {
      void client.invalidateQueries({ queryKey: ["reports"] });
      toast.show({ tone: "success", title: "Rapporten er laget", body: report.title });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/reports/${id}`),
    onSuccess: () => {
      setDeleting(null);
      void client.invalidateQueries({ queryKey: ["reports"] });
    },
  });

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (types.isPending) return <Spinner label="Henter rapporttyper …" />;
  if (types.error) return <Alert tone="danger" role="alert">{(types.error as Error).message}</Alert>;
  const selectedType = types.data.types.find((t) => t.value === type);

  const columns: Column<Report>[] = [
    { key: "title", header: "Rapport", rowHeader: true, cell: (r) => r.title },
    { key: "format", header: "Format", cell: (r) => <Badge>{r.format.toUpperCase()}</Badge> },
    { key: "created", header: "Laget", cell: (r) => formatDateTime(r.created_at) },
    { key: "size", header: "Størrelse", numeric: true, cell: (r) => formatSize(r.size) },
    {
      key: "actions",
      header: <span className="ek-visually-hidden">Handlinger</span>,
      cell: (r) => (
        <div className="ek-cluster" data-gap="2">
          {r.format === "html" ? (
            <a className="ek-btn ek-btn--sm" href={`/api/reports/${r.id}/view`} target="_blank" rel="noreferrer noopener">
              <ExternalIcon aria-hidden="true" />
              Åpne<span className="ek-visually-hidden">: {r.title} (åpnes i ny fane)</span>
            </a>
          ) : null}
          <a className="ek-btn ek-btn--sm" href={`/api/reports/${r.id}/download`} download={r.filename}>
            <Download aria-hidden="true" />
            Last ned<span className="ek-visually-hidden">: {r.title}</span>
          </a>
          <Button size="sm" variant="ghost" icon={<Trash aria-hidden="true" />} onClick={() => setDeleting(r)}>
            Slett<span className="ek-visually-hidden">: {r.title}</span>
          </Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Rapporter" description="Rapporter bygger på de siste analysene som er lagret i EmneKlar. De inneholder ingen studentdata."
        actions={<HelpLink topic="rapporter" />} />
      <div className="ek-stack" data-gap="6">
        <Card title="Lag rapport" headingLevel={2}>
          <div className="ek-stack" data-gap="6">
            <RadioGroup legend="Rapporttype" name="report-type" variant="card" value={type} onChange={setType}
              options={types.data.types.map((t) => ({
                value: t.value,
                label: t.label,
                hint: `${TYPE_HINTS[t.value] ?? ""}${t.analysed ? "" : " Ikke analysert ennå."}`,
              }))} />
            <RadioGroup legend="Format" name="report-format" value={format} onChange={setFormat}
              options={types.data.formats.map((f) => ({ value: f.value, label: f.label }))} />
            <p className="ek-small ek-muted">
              PDF: åpne HTML-rapporten og velg «Skriv ut» → «Lagre som PDF» i nettleseren. Rapporten er tilpasset utskrift.
            </p>
            {selectedType && !selectedType.analysed ? (
              <Alert tone="info" title="Ingen analyse ennå"
                actions={<Button size="sm" onClick={() => ui.openAnalysis()}>Kjør analyse</Button>}>
                Kjør en analyse av emnet før du lager denne rapporten.
              </Alert>
            ) : null}
            <div>
              <Button variant="primary" icon={<FileChartColumn aria-hidden="true" />} onClick={() => create.mutate()}
                loading={create.isPending} disabled={!selectedType?.analysed}>
                Lag rapport
              </Button>
            </div>
            {create.error ? <Alert tone="danger" role="alert">{(create.error as Error).message}</Alert> : null}
            <p className="ek-xs ek-muted">
              Rapportene beskriver funn fra automatiske og delvis automatiske kontroller. De er ikke en erklæring om at
              emnet er universelt utformet.
            </p>
          </div>
        </Card>
        <section className="ek-stack" aria-labelledby="rapporter">
          <h2 id="rapporter">Lagrede rapporter</h2>
          {reports.isPending ? <Spinner label="Henter rapporter …" /> : (
            <DataTable caption="Lagrede rapporter" captionHidden columns={columns} rows={reports.data?.items ?? []}
              rowKey={(r) => r.id} empty="Ingen rapporter for dette emnet ennå." />
          )}
        </section>
      </div>
      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
        title="Slette rapporten?"
        confirmLabel="Slett rapporten"
        danger
        loading={remove.isPending}
      >
        <p>Rapportfilen slettes fra denne maskinen. Analysene og funnene i EmneKlar påvirkes ikke.</p>
      </ConfirmDialog>
    </>
  );
}

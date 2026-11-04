// Steps 5 and 6 – Generer og Gjennomgå: the course overview (module → page → images) with status, bulk approval,
// generation of a planned run, and the detail view for each illustration.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Eye, Globe, Images, Play, RotateCcw, ThumbsUp, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { AiBadge } from "../../../core/ai";
import { api } from "../../../core/api/client";
import type { Job } from "../../../core/api/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ImageFrame,
  KeyFigure,
  KeyFigureList,
  Spinner,
  useToast,
} from "../../../design-system";
import { JobRunner } from "../../analysis/JobRunner";
import { FINAL_STATUSES } from "../../analysis/useJob";
import { ILLUSTRATION_TONE, money, RUN_TONE, useRun, type Catalog, type Illustration, type OverviewPage, type RunDetail } from "./api";
import { JOB_WORDING } from "./AnalyseStep";
import { IllustrationDetail, PagePreviewDialog } from "./IllustrationDetail";

function pageLine(page: OverviewPage): string {
  const n = page.proposed;
  if (page.status === "failed") return `Feilet: ${page.reason ?? ""}`;
  if (page.status === "pending") return "Ikke analysert ennå";
  if (n === 0) return "Ingen bilder nødvendig";
  return `${n} foreslått${n === 1 ? "" : "e"} bilde${n === 1 ? "" : "r"}`;
}

function Thumb({ item, onOpen }: { item: Illustration; onOpen: () => void }) {
  const placeholder = item.status === "skipped" ? "Hoppet over" : item.status === "proposed" ? "Foreslått – ikke generert"
    : item.status === "failed" ? "Feilet" : "Lages …";
  return (
    <button type="button" className="ek-thumb-button" onClick={onOpen}
      aria-label={`${item.plan.concept ?? "Illustrasjon"} – ${item.status_label}. Åpne detaljer`}>
      <ImageFrame size="thumb" src={item.thumb_url} alt="" placeholder={placeholder} />
      <span className="ek-small ek-strong">{item.plan.concept ?? item.section.title}</span>
      <span className="ek-cluster" data-gap="1">
        <Badge tone={ILLUSTRATION_TONE[item.status] ?? "neutral"}>{item.status_label}</Badge>
        {item.manual_check ? <Badge tone="warning">Manuell kontroll</Badge> : null}
        {item.labels.length ? <Badge>Med etiketter</Badge> : null}
      </span>
      <span className="ek-small ek-muted">{item.placement_label}{item.section.title ? ` – «${item.section.title}»` : ""}</span>
    </button>
  );
}

export function ReviewStep({ runId, catalog, onPublish }: { runId: number; catalog: Catalog; onPublish: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const run = useRun(runId);
  const [openId, setOpenId] = useState<number | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: ["illustrations"] });
  const bulk = useMutation({
    mutationFn: (body: { level: "page" | "module" | "course" | "ids"; page_url?: string; module_id?: string; ids?: number[]; action?: string }) =>
      api.post<{ changed: number[]; missing_alt_text: number[] }>("/api/illustrations/bulk", { run_id: runId, ...body }),
    onSuccess: async (r) => {
      await refresh();
      toast.show({ tone: r.missing_alt_text.length ? "warning" : "success",
        title: `${r.changed.length} bilde${r.changed.length === 1 ? "" : "r"} oppdatert`,
        body: r.missing_alt_text.length ? `${r.missing_alt_text.length} mangler alternativ tekst og ble ikke godkjent.` : undefined });
    },
  });
  const include = useMutation({
    mutationFn: ({ id, on }: { id: number; on: boolean }) => api.patch(`/api/illustrations/${id}`, { status: on ? "proposed" : "skipped" }),
    onSuccess: refresh,
  });
  const generate = useMutation({
    mutationFn: () => api.post<Job>(`/api/illustrations/runs/${runId}/generate`, { confirmed: true }),
    onSuccess: (job) => setJobId(job.id),
  });
  const resume = useMutation({
    mutationFn: () => api.post<Job>(`/api/illustrations/runs/${runId}/continue`, { confirmed: true }),
    onSuccess: (job) => setJobId(job.id),
  });

  if (run.isPending) return <Spinner label="Henter kjøringen …" />;
  if (run.error || !run.data) return <Alert tone="danger">Kunne ikke hente kjøringen.</Alert>;
  const data: RunDetail = run.data;
  const activeJob = jobId ?? (data.job && !FINAL_STATUSES.has(data.job.status) ? data.job.id : null);
  const counts = data.counts;
  const all = data.illustrations;
  const open = all.find((i) => i.id === openId) ?? null;
  const usage = data.run.usage;
  const proposed = counts.proposed ?? 0;
  const approved = counts.approved ?? 0;

  return (
    <div className="ek-stack" data-gap="6">
      <Card title="4. Generer og gjennomgå"
        description="Lag bildene, se dem på siden og godkjenn, avvis, endre eller lag dem på nytt – ett bilde, en side, en modul eller alt på én gang."
        actions={<Badge tone={RUN_TONE[data.run.status] ?? "neutral"}>{data.run.status_label}</Badge>}>
        <div className="ek-stack" data-gap="4">
          <KeyFigureList label="Status">
            <KeyFigure icon={<Images />} tone="info" value={all.filter((i) => i.status !== "skipped").length} label="Foreslåtte bilder" />
            <KeyFigure icon={<Eye />} tone="violet" value={(counts.generated ?? 0) + (counts.flagged ?? 0)} label="Klare til gjennomgang" />
            <KeyFigure icon={<TriangleAlert />} tone="warning" value={counts.flagged ?? 0} label="Må kontrolleres" />
            <KeyFigure icon={<ThumbsUp />} tone="success" value={approved} label="Godkjent" />
            <KeyFigure icon={<Globe />} tone="success" value={counts.published ?? 0} label="Publisert" />
          </KeyFigureList>
          <p className="ek-small ek-muted">
            Forbruk så langt: {money(usage.cost_usd ?? 0, usage.currency)} ({usage.calls ?? 0} kall
            {usage.unreported_calls ? `, ${usage.unreported_calls} uten bruksdata fra leverandøren – anslått` : ""}). Beløpet er et anslag ut fra veiledende priser.
          </p>
          {data.run.error ? <Alert tone="warning">{data.run.error}</Alert> : null}
          {data.run.limitations.map((l) => <p key={l} className="ek-small ek-muted">{l}</p>)}
          {activeJob ? (
            <JobRunner jobId={activeJob} wording={JOB_WORDING} onDone={() => {
              setJobId(null);
              void refresh();
            }} />
          ) : (
            <div className="ek-cluster" data-gap="2">
              {proposed > 0 ? (
                <Button variant="primary" icon={<Play aria-hidden="true" />} onClick={() => generate.mutate()} loading={generate.isPending}>
                  Generer {proposed} bilde{proposed === 1 ? "" : "r"}
                </Button>
              ) : null}
              {data.can_continue ? (
                <Button icon={<RotateCcw aria-hidden="true" />} onClick={() => resume.mutate()} loading={resume.isPending}>Fortsett der jobben stoppet</Button>
              ) : null}
              <Button icon={<CircleCheck aria-hidden="true" />} onClick={() => bulk.mutate({ level: "course" })} loading={bulk.isPending && bulk.variables?.level === "course"}
                disabled={!((counts.generated ?? 0) + (counts.flagged ?? 0))}>
                Godkjenn alle bildene
              </Button>
              <Button variant="primary" onClick={onPublish} disabled={!approved}>Gå til publisering ({approved})</Button>
            </div>
          )}
          {generate.error || resume.error ? <Alert tone="danger">{(generate.error ?? resume.error)?.message}</Alert> : null}
          <AiBadge />
        </div>
      </Card>
      {data.overview.length === 0 ? (
        <EmptyState title="Ingen sider analysert ennå">Når analysen er ferdig, vises modulene og sidene her.</EmptyState>
      ) : data.overview.map((module) => (
        <Card key={module.module_id} title={module.name} headingLevel={3}
          description={`${module.pages.length} side${module.pages.length === 1 ? "" : "r"}, ${module.proposed} foreslått${module.proposed === 1 ? "" : "e"} bilde${module.proposed === 1 ? "" : "r"}`}
          actions={module.pages.some((p) => p.illustrations.some((i) => i.status === "generated" || i.status === "flagged")) ? (
            <Button size="sm" onClick={() => bulk.mutate({ level: "module", module_id: module.module_id })}>Godkjenn modulen</Button>
          ) : null}>
          <div className="ek-stack" data-gap="5">
            {module.pages.map((page) => (
              <section key={page.page_url} className="ek-stack" data-gap="2" aria-label={page.title}>
                <div className="ek-cluster" data-justify="between">
                  <div className="ek-stack" data-gap="1">
                    <h4>{page.title}</h4>
                    <span className="ek-small ek-muted">{pageLine(page)}{page.proposed === 0 && page.reason ? ` – ${page.reason}` : ""}</span>
                  </div>
                  <div className="ek-cluster" data-gap="2">
                    {page.illustrations.some((i) => i.asset_id) ? (
                      <Button size="sm" onClick={() => setPreviewId(page.illustrations.find((i) => i.asset_id)?.id ?? null)}>Forhåndsvis siden</Button>
                    ) : null}
                    {page.illustrations.some((i) => i.status === "generated" || i.status === "flagged") ? (
                      <Button size="sm" onClick={() => bulk.mutate({ level: "page", page_url: page.page_url })}>Godkjenn alle på siden</Button>
                    ) : null}
                  </div>
                </div>
                {page.illustrations.length ? (
                  <div className="ek-thumb-grid">
                    {page.illustrations.map((item) => (
                      <div key={item.id} className="ek-stack" data-gap="1">
                        <Thumb item={item} onOpen={() => setOpenId(item.id)} />
                        {data.run.status === "planned" && (item.status === "proposed" || item.status === "skipped") ? (
                          <Checkbox label="Ta med" checked={item.status === "proposed"}
                            onChange={(e) => include.mutate({ id: item.id, on: e.target.checked })} />
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </section>
            ))}
          </div>
        </Card>
      ))}
      {open ? <IllustrationDetail item={open} catalog={catalog} onClose={() => setOpenId(null)} onJob={setJobId} /> : null}
      {previewId !== null ? <PagePreviewDialog illustrationId={previewId} onClose={() => setPreviewId(null)} /> : null}
    </div>
  );
}

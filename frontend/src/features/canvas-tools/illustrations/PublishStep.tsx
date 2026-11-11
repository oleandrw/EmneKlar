// Step 7 – Publiser: shows exactly what changes before anything is sent, then publishes through the change engine.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "../../../core/api/client";
import type { Job } from "../../../core/api/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  ImageFrame,
  RadioGroup,
  SelectField,
  Spinner,
  TextField,
  useToast,
} from "../../../design-system";
import { JobRunner } from "../../analysis/JobRunner";
import { useRun, type Catalog, type PublishPreview } from "./api";

type Mode = "publish" | "queue";

export function PublishStep({ runId, catalog }: { runId: number; catalog: Catalog }) {
  const client = useQueryClient();
  const toast = useToast();
  const run = useRun(runId);
  const [mode, setMode] = useState<Mode>("publish");
  const [rights, setRights] = useState("");
  const [copyright, setCopyright] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [undoPage, setUndoPage] = useState<string | null>(null);
  const approvedCount = run.data?.counts.approved ?? 0;
  const preview = useQuery({
    queryKey: ["illustrations", "publish-preview", runId, approvedCount],
    queryFn: () => api.post<PublishPreview>(`/api/illustrations/runs/${runId}/publish/preview`, {}),
    enabled: approvedCount > 0,
  });
  const usageRights = rights ? { use_justification: rights, legal_copyright: copyright || null } : null;
  const publish = useMutation({
    mutationFn: () => api.post<{ job: Job | null; errors: { title: string; message: string }[]; changes: unknown[] }>(
      `/api/illustrations/runs/${runId}/publish`, { usage_rights: usageRights, apply: mode === "publish" }),
    onSuccess: async (r) => {
      if (r.job) setJobId(r.job.id);
      else toast.show({ tone: "success", title: `${r.changes.length} side${r.changes.length === 1 ? "" : "r"} lagt i endringskøen` });
      await client.invalidateQueries({ queryKey: ["illustrations"] });
      await client.invalidateQueries({ queryKey: ["changes"] });
    },
  });
  const undo = useMutation({
    mutationFn: (page_url: string) => api.post(`/api/illustrations/runs/${runId}/undo`, { page_url }),
    onSuccess: async () => {
      setUndoPage(null);
      toast.show({ tone: "success", title: "Illustrasjonene på siden er fjernet" });
      await client.invalidateQueries({ queryKey: ["illustrations"] });
      await client.invalidateQueries({ queryKey: ["changelog"] });
    },
  });

  if (run.isPending) return <Spinner label="Henter kjøringen …" />;
  const published = (run.data?.illustrations ?? []).filter((i) => i.status === "published");
  const publishedPages = [...new Map(published.map((i) => [i.page_url, i.page_title])).entries()];
  const dropped = [...new Set(published.flatMap((i) => i.published.html_check?.dropped ?? []))];
  const data = preview.data;
  const rightsMissing = Boolean(data?.usage_rights_required && !rights);
  const okPages = data?.pages.filter((p) => p.ok) ?? [];
  const images = okPages.reduce((n, p) => n + p.illustrations.length, 0);

  return (
    <div className="ek-stack" data-gap="6">
      <Card title="5. Publiser" description="Bare godkjente bilder publiseres. De settes inn på riktig sted via endringskøen: konfliktsjekk, sikkerhetskopi, logg og angremulighet.">
        <div className="ek-stack" data-gap="5">
          {jobId ? (
            <JobRunner jobId={jobId} wording={{ noun: "publiseringen", current: "Nå publiseres", findingsTitle: "Resultat", findingsEmpty: "",
              cancelNote: "Sider som allerede er oppdatert, beholdes og kan angres fra endringsloggen." }}
              onDone={() => {
                setJobId(null);
                void client.invalidateQueries({ queryKey: ["illustrations"] });
                void client.invalidateQueries({ queryKey: ["changes"] });
                void client.invalidateQueries({ queryKey: ["changelog"] });
              }} />
          ) : approvedCount === 0 ? (
            <p>Ingen godkjente bilder venter på publisering. Godkjenn bilder i steg 4.</p>
          ) : preview.isPending ? <Spinner label="Beregner hva som endres …" /> : preview.error ? (
            <Alert tone="danger">{preview.error.message}</Alert>
          ) : data ? (
            <>
              <RadioGroup<Mode> legend="Hvordan vil du publisere?" name="illustration-publish" value={mode} onChange={setMode} variant="card" columns={2}
                options={[
                  { value: "publish", label: "Gjennomgå og godkjenn (standard)", hint: "Du har godkjent bildene. Sidene oppdateres nå, side for side." },
                  { value: "queue", label: "Legg i endringskøen", hint: "Sidene legges i den globale endringskøen, der du kan se forskjellen og gjennomføre senere." },
                ]} />
              <p className="ek-small">{data.note}</p>
              <ul className="ek-stack" data-gap="4">
                {data.pages.map((page) => (
                  <li key={page.page_url} className="ek-stack" data-gap="2">
                    <div className="ek-cluster" data-gap="2">
                      <strong>{page.title}</strong>
                      {page.ok ? <Badge tone="info">{page.illustrations.length} bilde{page.illustrations.length === 1 ? "" : "r"} settes inn</Badge>
                        : <Badge tone="danger">Kan ikke publiseres</Badge>}
                      {page.published === false ? <Badge>Siden er ikke publisert – det beholdes</Badge> : null}
                      {page.replaces?.length ? <Badge tone="warning">Erstatter en tidligere versjon fra EmneKlar</Badge> : null}
                    </div>
                    {page.error ? <p className="ek-small">{page.error}</p> : null}
                    <div className="ek-thumb-grid">
                      {page.illustrations.map((i) => (
                        <div key={i.id} className="ek-stack" data-gap="1">
                          <ImageFrame size="thumb" src={i.thumb_url ?? null} alt={i.decorative ? "" : i.alt_text ?? ""} />
                          <span className="ek-small">{i.placement_label}{i.section ? ` – «${i.section}»` : ""}</span>
                          <span className="ek-small ek-muted">Alt-tekst: {i.decorative ? "(dekorativt)" : i.alt_text}</span>
                          {i.caption ? <span className="ek-small ek-muted">Bildetekst: {i.caption}</span> : null}
                        </div>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
              {data.usage_rights_required ? (
                <div className="ek-grid" data-cols="2" data-gap="4">
                  <SelectField label="Opphavsrettsgrunnlag" value={rights} onChange={(e) => setRights(e.target.value)} placeholder="Velg grunnlag"
                    hint="Emnet krever opphavsrettsinformasjon. Uten den blir bildene låst og usynlige for studentene. Du må selv vurdere riktig grunnlag."
                    options={catalog.usage_rights.map((u) => ({ value: u.id, label: u.label }))} />
                  <TextField label="Opphavsrettslinje" optional value={copyright} onChange={(e) => setCopyright(e.target.value)} />
                </div>
              ) : null}
              {publish.error ? <Alert tone="danger">{publish.error.message}</Alert> : null}
              {publish.data?.errors.length ? (
                <Alert tone="warning" title="Noen sider ble ikke lagt i køen">
                  <ul>{publish.data.errors.map((e) => <li key={e.title}>{e.title}: {e.message}</li>)}</ul>
                </Alert>
              ) : null}
              <div>
                <Button variant="primary" size="lg" icon={<Send aria-hidden="true" />} disabled={!images || rightsMissing}
                  loading={publish.isPending} onClick={() => publish.mutate()}>
                  {mode === "publish" ? `Publiser ${images} bilde${images === 1 ? "" : "r"} på ${okPages.length} side${okPages.length === 1 ? "" : "r"}`
                    : "Legg i endringskøen"}
                </Button>
              </div>
            </>
          ) : null}
        </div>
      </Card>
      <Card title="Publiserte illustrasjoner" description="Angring fjerner bare figurene EmneKlar satte inn – endringer du har gjort på siden etterpå, beholdes.">
        {publishedPages.length === 0 ? <p className="ek-small ek-muted">Ingen illustrasjoner fra denne kjøringen er publisert ennå.</p> : (
          <ul className="ek-stack" data-gap="2">
            {publishedPages.map(([url, title]) => (
              <li key={url} className="ek-cluster" data-justify="between">
                <span>{title}</span>
                <Button size="sm" icon={<Undo2 aria-hidden="true" />} onClick={() => setUndoPage(url)}>Angre på denne siden</Button>
              </li>
            ))}
          </ul>
        )}
        {published.length ? (
          <p className="ek-small">
            Kontroll etter publisering: figur, bilde, alternativ tekst og bildetekst er bevart i Canvas.
            {dropped.length ? ` Canvas fjernet disse attributtene ved lagring: ${dropped.join(", ")}. Bildet vises likevel riktig.` : " Alle attributtene ble beholdt."}
          </p>
        ) : null}
        <p className="ek-small ek-muted">Alle endringer finnes også i <Link to="/canvas-verktoy/endringslogg">Sikkerhetskopier og endringslogg</Link>.</p>
        {undo.error ? <Alert tone="danger">{undo.error.message}</Alert> : null}
      </Card>
      <ConfirmDialog open={undoPage !== null} onClose={() => setUndoPage(null)} onConfirm={() => undoPage && undo.mutate(undoPage)}
        title="Fjerne illustrasjonene fra siden?" confirmLabel="Fjern illustrasjonene" loading={undo.isPending}>
        Figurene EmneKlar satte inn, fjernes fra siden i Canvas. All annen tekst og alt du har endret selv, beholdes. Bildefilene blir liggende i Canvas-filene.
      </ConfirmDialog>
    </div>
  );
}

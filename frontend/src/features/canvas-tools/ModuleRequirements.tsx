// «Automatiske modulkrav»: completion requirements per item type, previewed and staged through the change queue.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, ListPlus } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { useSession } from "../../core/session";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Card,
  Checkbox,
  DataTable,
  EmptyState,
  Fieldset,
  PageHeader,
  RadioGroup,
  SelectField,
  Spinner,
  TextField,
  Button,
  useToast,
  type Column,
  type Tone,
} from "../../design-system";
import type { ContentIndex } from "./shared";

interface Options {
  item_types: { type: string; label: string; default: string | null; allowed: { value: string; label: string }[] }[];
  statuses: Record<string, string>;
}

interface Row {
  item_id: string;
  title: string;
  type: string;
  type_label: string;
  current_label: string;
  proposed_label: string;
  status: "add" | "replace" | "remove" | "keep" | "unchanged" | "none" | "not_applicable";
  status_label: string;
  notes: string[];
}

interface Preview {
  modules: {
    id: string;
    name: string;
    published: boolean | null;
    requirement_type: "all" | "one" | null;
    items: Row[];
    settings: { current: Record<string, unknown>; proposed: Record<string, unknown>; changed: Record<string, unknown> };
  }[];
  counts: Record<string, number>;
  warnings: string[];
  changes: number;
}

const STATUS_TONE: Record<Row["status"], Tone> = {
  add: "success", replace: "warning", remove: "danger", keep: "info", unchanged: "neutral", none: "neutral",
  not_applicable: "neutral",
};

export function ModuleRequirements() {
  const { courseId } = useCurrentCourse();
  const session = useSession();
  const ui = useUi();
  const toast = useToast();
  const client = useQueryClient();
  const options = useQuery({ queryKey: ["requirement-options"], queryFn: () => api.get<Options>("/api/module-requirements/options"), staleTime: Infinity });
  const index = useQuery({
    queryKey: ["content-index", courseId],
    queryFn: () => api.get<ContentIndex>(`/api/courses/${courseId}/content-index`),
    enabled: Boolean(courseId),
  });
  const [scope, setScope] = useState<"course" | "modules">("course");
  const [moduleIds, setModuleIds] = useState<string[]>([]);
  const [existing, setExisting] = useState<"keep" | "replace">("keep");
  const [policy, setPolicy] = useState<Record<string, string>>({});
  const [minScore, setMinScore] = useState("");
  const [sequential, setSequential] = useState("");
  const [previewed, setPreviewed] = useState<{ key: string; data: Preview } | null>(null);

  const effectivePolicy = useMemo(() => {
    const result: Record<string, string | null> = {};
    for (const t of options.data?.item_types ?? []) {
      const chosen = policy[t.type] ?? t.default ?? "";
      result[t.type] = chosen || null;
    }
    return result;
  }, [options.data, policy]);
  const usesMinScore = Object.values(effectivePolicy).includes("min_score");
  const body = {
    module_ids: scope === "modules" ? moduleIds : [], existing, policy: effectivePolicy,
    min_score: usesMinScore && minScore ? Number(minScore) : null,
    require_sequential_progress: sequential === "" ? null : sequential === "yes",
  };
  const key = JSON.stringify(body);
  // The key includes the policy derived from the options, so a preview is only shown for the choices it was made
  // for. «Forhåndsvis» waits for the options: a preview requested before they load would never match.
  const preview = previewed?.key === key ? previewed.data : null;
  const previewMutation = useMutation({
    mutationFn: async (request: { key: string; body: typeof body }) => ({
      key: request.key,
      data: await api.post<Preview>(`/api/courses/${courseId}/module-requirements/preview`, request.body),
    }),
    onSuccess: setPreviewed,
  });
  const stage = useMutation({
    mutationFn: () => api.post<{ staged: number }>(`/api/courses/${courseId}/module-requirements/stage`, body),
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: ["changes"] });
      toast.show({
        tone: "success",
        title: `${result.staged} endringer lagt i endringskøen`,
        body: session.dry_run ? "Dry run er på – ingenting sendes til Canvas før du slår det av." : "Gjennomfør dem fra endringskøen.",
      });
      ui.openChanges();
    },
  });

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  const columns: Column<Row>[] = [
    { key: "title", header: "Element", rowHeader: true, cell: (r) => (
      <span className="ek-stack" data-gap="1">
        <span>{r.title}</span>
        {r.notes.map((n) => <span key={n} className="ek-xs ek-muted">{n}</span>)}
      </span>
    ) },
    { key: "type", header: "Type", cell: (r) => r.type_label },
    { key: "current", header: "Nåværende", cell: (r) => r.current_label },
    { key: "proposed", header: "Foreslått", cell: (r) => r.proposed_label },
    { key: "status", header: "Status", cell: (r) => <Badge tone={STATUS_TONE[r.status]}>{r.status_label}</Badge> },
  ];

  return (
    <>
      <PageHeader title="Automatiske modulkrav" description="Foreslår fullføringskrav ut fra elementtype. Bare kombinasjoner Canvas støtter, kan velges." />
      <div className="ek-stack" data-gap="6">
        <Card title="Valg" headingLevel={2}>
          <div className="ek-stack" data-gap="6">
            <RadioGroup legend="Omfang" name="scope" value={scope} onChange={setScope}
              options={[{ value: "course", label: "Hele emnet" }, { value: "modules", label: "Valgte moduler" }]} />
            {scope === "modules" ? (
              index.isPending ? <Spinner label="Henter moduler …" /> : (
                <Fieldset legend="Moduler">
                  {(index.data?.modules ?? []).map((m) => (
                    <Checkbox key={m.id} label={`${m.name} (${m.items_count} elementer)`} checked={moduleIds.includes(m.id)}
                      onChange={(e) => setModuleIds(e.target.checked ? [...moduleIds, m.id] : moduleIds.filter((x) => x !== m.id))} />
                  ))}
                </Fieldset>
              )
            ) : null}
            <RadioGroup legend="Eksisterende krav" name="existing" value={existing} onChange={setExisting}
              options={[
                { value: "keep", label: "Behold eksisterende", hint: "Anbefalt. Elementer som allerede har krav, endres ikke." },
                { value: "replace", label: "Erstatt eksisterende", hint: "Eksisterende krav byttes ut med forslaget." },
              ]} />
            {options.isPending ? <Spinner label="Henter krav per elementtype …" /> : null}
            {options.error ? (
              <Alert tone="danger" role="alert">{(options.error as Error).message}</Alert>
            ) : null}
            {options.data ? (
              <Fieldset legend="Krav per elementtype">
                <div className="ek-grid" data-cols="2">
                  {options.data.item_types.map((t) => (
                    <SelectField key={t.type} label={t.label} value={policy[t.type] ?? t.default ?? ""}
                      disabled={t.allowed.length === 0}
                      hint={t.allowed.length === 0 ? "Canvas støtter ikke krav for denne typen." : undefined}
                      onChange={(e) => setPolicy({ ...policy, [t.type]: e.target.value })}
                      options={[{ value: "", label: "Ingen krav" }, ...t.allowed]} />
                  ))}
                </div>
              </Fieldset>
            ) : null}
            {usesMinScore ? (
              <TextField label="Minstepoeng" type="number" min={0} value={minScore} onChange={(e) => setMinScore(e.target.value)} />
            ) : null}
            <div className="ek-grid" data-cols="2">
              <SelectField label="Må kravene fullføres i rekkefølge?" value={sequential} onChange={(e) => setSequential(e.target.value)}
                options={[{ value: "", label: "Ikke endre" }, { value: "yes", label: "Ja, i rekkefølge" }, { value: "no", label: "Nei, fritt" }]} />
            </div>
            <p className="ek-small ek-muted">
              Om studentene må fullføre alle kravene eller bare ett av dem, kan ikke endres gjennom Canvas-API-et.
              Endre det i modulens innstillinger i Canvas. Forhåndsvisningen viser hva hver modul bruker i dag.
            </p>
            <div className="ek-cluster">
              <Button icon={<Eye aria-hidden="true" />} onClick={() => previewMutation.mutate({ key, body })} loading={previewMutation.isPending}
                disabled={!options.data || (scope === "modules" && moduleIds.length === 0)}>
                Forhåndsvis
              </Button>
              <Button variant="primary" icon={<ListPlus aria-hidden="true" />} onClick={() => stage.mutate()} loading={stage.isPending}
                disabled={!preview || preview.changes === 0} title={preview ? undefined : "Forhåndsvis først"}>
                {preview ? `Legg ${preview.changes} endringer i kø` : "Legg endringer i kø"}
              </Button>
            </div>
            {previewMutation.error || stage.error ? (
              <Alert tone="danger" role="alert">{((previewMutation.error ?? stage.error) as Error).message}</Alert>
            ) : null}
          </div>
        </Card>

        {preview ? (
          <section className="ek-stack" aria-labelledby="forhandsvisning">
            <h2 id="forhandsvisning">Forhåndsvisning</h2>
            <p className="ek-small" aria-live="polite">
              {preview.changes} endringer: {preview.counts.add ?? 0} nye krav, {preview.counts.replace ?? 0} erstattes,{" "}
              {preview.counts.remove ?? 0} fjernes, {preview.counts.keep ?? 0} beholdes.
            </p>
            {preview.warnings.length ? (
              <Alert tone="warning" title="Merk">
                <ul>{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              </Alert>
            ) : null}
            {preview.modules.map((m) => (
              <Card key={m.id} title={m.name} headingLevel={3}
                actions={m.requirement_type === "one" || Object.keys(m.settings.changed).length ? (
                  <>
                    {m.requirement_type === "one" ? <Badge tone="info">Ett av kravene må fullføres</Badge> : null}
                    {Object.keys(m.settings.changed).length ? <Badge tone="warning">Modulinnstillinger endres</Badge> : null}
                  </>
                ) : null}>
                <DataTable caption={`Elementer i ${m.name}`} captionHidden columns={columns} rows={m.items} rowKey={(r) => r.item_id}
                  empty="Modulen har ingen elementer." />
              </Card>
            ))}
          </section>
        ) : null}
      </div>
    </>
  );
}

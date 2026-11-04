// «Blueprint-låsing»: detect Blueprint status, preview lock/unlock, stage one high-risk change.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, ListPlus, Lock } from "lucide-react";
import { useState } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime } from "../../core/format";
import { useSession } from "../../core/session";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  EmptyState,
  Fieldset,
  KeyValue,
  PageHeader,
  RadioGroup,
  Spinner,
  useToast,
  type Column,
} from "../../design-system";

interface Item {
  content_type: string;
  content_id: string;
  title: string;
  type_label: string;
  restricted: boolean | null;
  restrictions: Record<string, boolean> | null;
  modules: string[];
  module_ids: string[];
}

type BlueprintData =
  | { available: false; reason: string; is_child: boolean; parent: string | null }
  | {
      available: true;
      template: { associated_course_count: number | null; last_export_completed_at: string | null };
      items: Item[];
      modules: { id: string; name: string }[];
      counts: Record<string, { total: number; locked: number; unknown: number }>;
      content_types: { value: string; label: string }[];
      restriction_options: { value: string; label: string }[];
      note: string;
    };

interface PreviewRow extends Item {
  proposed: boolean;
  status: "change" | "unchanged" | "unknown";
  status_label: string;
}

const lockLabel = (value: boolean | null) => (value === null ? "Ukjent" : value ? "Låst" : "Ulåst");

/** «3 av 10 låst», or a truthful note when Canvas does not report the lock status. */
function countLabel(count: { total: number; locked: number; unknown: number } | undefined): string {
  if (!count || count.total === 0) return "Ingen";
  if (count.unknown === count.total) return `${count.total} – låsestatus vises ikke av Canvas`;
  const known = count.total - count.unknown;
  const base = `${count.locked} av ${known} låst`;
  return count.unknown ? `${base} (${count.unknown} med ukjent status)` : base;
}

export function BlueprintLocking() {
  const { courseId } = useCurrentCourse();
  const session = useSession();
  const ui = useUi();
  const toast = useToast();
  const client = useQueryClient();
  const data = useQuery({
    queryKey: ["blueprint", courseId],
    queryFn: () => api.get<BlueprintData>(`/api/courses/${courseId}/blueprint`),
    enabled: Boolean(courseId),
  });
  const [action, setAction] = useState<"lock" | "unlock">("lock");
  const [types, setTypes] = useState<string[] | null>(null);
  const [moduleIds, setModuleIds] = useState<string[]>([]);
  const [custom, setCustom] = useState(false);
  const [restrictions, setRestrictions] = useState<string[]>(["content"]);
  const [previewed, setPreviewed] = useState<{ key: string; rows: PreviewRow[] } | null>(null);

  const allTypes = data.data?.available ? data.data.content_types.map((t) => t.value) : [];
  const chosenTypes = types ?? allTypes;
  const body = {
    action, content_types: chosenTypes, module_ids: moduleIds,
    restrictions: action === "lock" && custom ? Object.fromEntries(restrictions.map((r) => [r, true])) : null,
  };
  const key = JSON.stringify(body);
  const rows = previewed?.key === key ? previewed.rows : null;
  const preview = useMutation({
    mutationFn: async (request: { key: string; body: typeof body }) => ({
      key: request.key,
      rows: (await api.post<{ rows: PreviewRow[] }>(`/api/courses/${courseId}/blueprint/preview`, request.body)).rows,
    }),
    onSuccess: setPreviewed,
  });
  const stage = useMutation({
    mutationFn: () => api.post(`/api/courses/${courseId}/blueprint/stage`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["changes"] });
      toast.show({
        tone: "success",
        title: "Blueprint-endringen er lagt i endringskøen",
        body: session.dry_run ? "Dry run er på – ingenting sendes til Canvas." : "Endringen krever ekstra bekreftelse når du gjennomfører den.",
      });
      ui.openChanges();
    },
  });

  const header = <PageHeader title="Blueprint-låsing" description="Lås eller lås opp innhold i et Blueprint-emne, slik at tilknyttede emner ikke kan endre det." />;
  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (data.isPending) return <>{header}<Spinner label="Sjekker Blueprint-status …" /></>;
  if (data.error) return <>{header}<Alert tone="danger" role="alert">{(data.error as Error).message}</Alert></>;
  if (!data.data.available) {
    return (
      <>
        {header}
        <div className="ek-stack" data-gap="6">
          <EmptyState icon={<Lock aria-hidden="true" />} title="Ikke tilgjengelig for dette emnet">
            {data.data.reason}
          </EmptyState>
        </div>
      </>
    );
  }
  const bp = data.data;
  const changeCount = rows?.filter((r) => r.status !== "unchanged").length ?? 0;
  const columns: Column<PreviewRow>[] = [
    { key: "title", header: "Element", rowHeader: true, cell: (r) => r.title },
    { key: "type", header: "Type", cell: (r) => r.type_label },
    { key: "modules", header: "Modul", cell: (r) => r.modules.join(", ") || "–" },
    { key: "now", header: "Nå", cell: (r) => lockLabel(r.restricted) },
    { key: "after", header: "Etter", cell: (r) => lockLabel(r.proposed) },
    { key: "status", header: "Status", cell: (r) => (
      <Badge tone={r.status === "change" ? "warning" : r.status === "unknown" ? "info" : "neutral"}>{r.status_label}</Badge>
    ) },
  ];

  return (
    <>
      {header}
      <div className="ek-stack" data-gap="6">
        <Card title="Blueprint-emnet" headingLevel={2}>
          <div className="ek-stack">
            <KeyValue items={[
              ["Tilknyttede emner", String(bp.template.associated_course_count ?? "–")],
              ["Siste synkronisering", bp.template.last_export_completed_at ? formatDateTime(bp.template.last_export_completed_at) : "Ikke synkronisert"],
              ...bp.content_types.map((t) => [t.label, countLabel(bp.counts[t.value])] as [string, string]),
            ]} />
            <p className="ek-xs ek-muted">{bp.note} Endringer får virkning i tilknyttede emner ved neste synkronisering.</p>
          </div>
        </Card>
        <Card title="Lås eller lås opp" headingLevel={2}>
          <div className="ek-stack" data-gap="6">
            <RadioGroup legend="Handling" name="bp-action" value={action} onChange={setAction}
              options={[{ value: "lock", label: "Lås" }, { value: "unlock", label: "Lås opp" }]} />
            <Fieldset legend="Innholdstyper">
              {bp.content_types.map((t) => (
                <Checkbox key={t.value} label={t.label} checked={chosenTypes.includes(t.value)}
                  onChange={(e) => setTypes(e.target.checked ? [...chosenTypes, t.value] : chosenTypes.filter((x) => x !== t.value))} />
              ))}
            </Fieldset>
            {bp.modules.length ? (
              <Fieldset legend="Begrens til moduler" hint="Velg ingen for hele emnet.">
                {bp.modules.map((m) => (
                  <Checkbox key={m.id} label={m.name} checked={moduleIds.includes(m.id)}
                    onChange={(e) => setModuleIds(e.target.checked ? [...moduleIds, m.id] : moduleIds.filter((x) => x !== m.id))} />
                ))}
              </Fieldset>
            ) : null}
            {action === "lock" ? (
              <div className="ek-stack" data-gap="2">
                <Checkbox label="Velg selv hva som låses" checked={custom} onChange={(e) => setCustom(e.target.checked)}
                  hint="Ellers brukes standardinnstillingene for Blueprint-emnet." />
                {custom ? (
                  <Fieldset legend="Lås">
                    {bp.restriction_options.map((r) => (
                      <Checkbox key={r.value} label={r.label} checked={restrictions.includes(r.value)}
                        onChange={(e) => setRestrictions(e.target.checked ? [...restrictions, r.value] : restrictions.filter((x) => x !== r.value))} />
                    ))}
                  </Fieldset>
                ) : null}
              </div>
            ) : null}
            <div className="ek-cluster">
              <Button icon={<Eye aria-hidden="true" />} onClick={() => preview.mutate({ key, body })} loading={preview.isPending}
                disabled={chosenTypes.length === 0 || (custom && action === "lock" && restrictions.length === 0)}>
                Forhåndsvis
              </Button>
              <Button variant="primary" icon={<ListPlus aria-hidden="true" />} onClick={() => stage.mutate()} loading={stage.isPending}
                disabled={!rows || changeCount === 0} title={rows ? undefined : "Forhåndsvis først"}>
                {rows ? `Legg ${changeCount} elementer i kø` : "Legg i kø"}
              </Button>
            </div>
            {preview.error || stage.error ? (
              <Alert tone="danger" role="alert">{((preview.error ?? stage.error) as Error).message}</Alert>
            ) : null}
          </div>
        </Card>
        {rows ? (
          <DataTable caption="Forhåndsvisning" columns={columns} rows={rows} rowKey={(r) => `${r.content_type}:${r.content_id}`}
            empty="Ingen elementer med dette valget." />
        ) : null}
      </div>
    </>
  );
}

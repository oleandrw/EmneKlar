import { useState } from "react";

import { Button, DataTable, DiffView, HtmlPreview, type PreviewDevice } from "../../design-system";
import { formatHtml, HTML_FIELDS, type Change } from "./api";

const FIELD_LABELS: Record<string, string> = {
  title: "Tittel",
  module_id: "Modul",
  position: "Plassering",
  completion_requirement: "Fullføringskrav",
  requirement_type: "Krav i modulen",
  require_sequential_progress: "Krev rekkefølge",
  name: "Navn",
  default_view: "Startside",
  published: "Publisert",
  restricted: "Låst",
  items: "Elementer",
};

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "boolean") return value ? "Ja" : "Nei";
  if (typeof value === "object") {
    const v = value as Record<string, unknown>;
    if ("type" in v) return `${String(v.type)}${v.min_score !== undefined ? ` (${String(v.min_score)})` : ""}`;
    if (Array.isArray(value)) return `${value.length} element(er)`;
    return JSON.stringify(value);
  }
  return String(value);
}

export function ChangePreview({ change }: { change: Change }) {
  const [device, setDevice] = useState<PreviewDevice>("desktop");
  const htmlField = HTML_FIELDS.find((f) => typeof change.proposed[f] === "string");
  if (htmlField) {
    const before = String(change.before[htmlField] ?? "");
    const after = String(change.proposed[htmlField] ?? "");
    return (
      <div className="ek-stack">
        <DiffView before={formatHtml(before)} after={formatHtml(after)} beforeTitle="Nå i Canvas" afterTitle="Foreslått" />
        <div className="ek-cluster" role="group" aria-label="Visning">
          {(["desktop", "tablet", "mobile"] as PreviewDevice[]).map((d) => (
            <Button key={d} size="sm" variant={device === d ? "primary" : "secondary"} aria-pressed={device === d} onClick={() => setDevice(d)}>
              {{ desktop: "PC", tablet: "Nettbrett", mobile: "Mobil" }[d]}
            </Button>
          ))}
        </div>
        <HtmlPreview html={after} title={`Forhåndsvisning: ${change.title}`} device={device} />
      </div>
    );
  }
  if (change.kind === "blueprint.restrict") {
    const items = (change.proposed.items as { content_type: string; content_id: string; title?: string }[]) ?? [];
    return (
      <DataTable
        caption={`${change.proposed.restricted ? "Låses" : "Låses opp"}: ${items.length} element(er)`}
        columns={[
          { key: "title", header: "Element", cell: (r) => r.title ?? r.content_id, rowHeader: true },
          { key: "type", header: "Type", cell: (r) => r.content_type },
        ]}
        rows={items}
        rowKey={(r) => `${r.content_type}:${r.content_id}`}
      />
    );
  }
  const keys = Array.from(new Set([...Object.keys(change.proposed), ...Object.keys(change.before)])).filter((k) => !k.startsWith("_"));
  return (
    <DataTable
      caption="Endrede verdier"
      columns={[
        { key: "field", header: "Felt", cell: (k: string) => FIELD_LABELS[k] ?? k, rowHeader: true },
        { key: "before", header: "Nå", cell: (k: string) => show(change.before[k]) },
        { key: "after", header: "Foreslått", cell: (k: string) => (k in change.proposed ? show(change.proposed[k]) : "Uendret") },
      ]}
      rows={keys}
      rowKey={(k) => k}
    />
  );
}

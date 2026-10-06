import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useState } from "react";

import { api } from "../../core/api/client";
import { Alert, Badge, Button, DataTable, DiffView, HtmlPreview, KeyValue, Spinner, type PreviewDevice } from "../../design-system";
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
  front_page_url: "Forside",
  published: "Publisert",
  restricted: "Låst",
  items: "Elementer",
};
const REQUIREMENT_LABELS: Record<string, string> = {
  must_view: "Se på elementet",
  must_contribute: "Bidra",
  must_submit: "Levere",
  min_score: "Oppnå minstepoeng",
  must_mark_done: "Merke som ferdig",
};
const VALUE_LABELS: Record<string, string> = {
  feed: "Siste aktivitet", wiki: "Forside", modules: "Moduler", assignments: "Oppgaveliste", syllabus: "Emneplan",
  all: "Alle krav", one: "Ett av kravene",
};
const CONTENT_TYPE_LABELS: Record<string, string> = {
  wiki_page: "Side", assignment: "Oppgave", discussion_topic: "Diskusjon", quiz: "Quiz", attachment: "Fil",
};

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "boolean") return value ? "Ja" : "Nei";
  if (typeof value === "string") return VALUE_LABELS[value] ?? value;
  if (Array.isArray(value)) return `${value.length} ${value.length === 1 ? "element" : "elementer"}`;
  if (typeof value === "object") {
    const v = value as Record<string, unknown>;
    if ("type" in v) {
      const label = REQUIREMENT_LABELS[String(v.type)] ?? String(v.type);
      return `${label}${v.min_score !== undefined ? ` (${String(v.min_score)})` : ""}`;
    }
    return JSON.stringify(value);
  }
  return String(value);
}

interface Answer {
  text: string;
  correct: boolean;
}

function Answers({ answers, title }: { answers: Answer[]; title: string }) {
  return (
    <div className="ek-stack" data-gap="1">
      <span className="ek-strong ek-small">{title}</span>
      <ul className="ek-answers">
        {answers.map((a, i) => (
          <li key={i}>
            {a.correct ? <Badge tone="success" icon={<Check aria-hidden="true" size={14} />}>Riktig</Badge> : <Badge>Feil</Badge>}
            <span>{a.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HtmlChange({ change, field }: { change: Change; field: string }) {
  const [device, setDevice] = useState<PreviewDevice>("desktop");
  const before = String(change.before[field] ?? "");
  const after = String(change.proposed[field] ?? "");
  // Sanitised by the backend, with Canvas images shown through the local image proxy.
  const preview = useQuery({
    queryKey: ["changes", "preview", change.id, change.updated_at],
    queryFn: () => api.get<{ html: string | null }>(`/api/changes/${change.id}/preview`),
  });
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
      {preview.isPending ? <Spinner label="Lager forhåndsvisning …" /> : preview.error ? (
        <Alert tone="warning" role="alert">Forhåndsvisningen kunne ikke lages: {(preview.error as Error).message}</Alert>
      ) : (
        <HtmlPreview html={preview.data.html ?? ""} title={`Forhåndsvisning: ${change.title}`} device={device} />
      )}
    </div>
  );
}

export function ChangePreview({ change }: { change: Change }) {
  if (change.kind === "quiz.create") {
    const plan = change.proposed as {
      title: string;
      questions: { stem: string }[];
      summary: { questions_total: number; questions_asked: number; points_possible: number; published: boolean };
      warnings: string[];
    };
    return (
      <div className="ek-stack">
        <KeyValue items={[
          ["Tittel", plan.title],
          ["Spørsmål", plan.summary.questions_asked === plan.summary.questions_total
            ? String(plan.summary.questions_total) : `${plan.summary.questions_asked} av ${plan.summary.questions_total} (tilfeldig utvalg)`],
          ["Poeng", String(plan.summary.points_possible)],
          ["Status etter opprettelse", plan.summary.published ? "Publisert" : "Upublisert"],
        ]} />
        {plan.warnings.length ? <Alert tone="warning" title="Canvas vil ignorere noen innstillinger"><ul>{plan.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Alert> : null}
        <ol className="ek-small">{plan.questions.map((q, i) => <li key={i}>{q.stem}</li>)}</ol>
      </div>
    );
  }
  if (change.kind === "quiz_question.update") {
    const beforeAnswers = (change.before.answers as Answer[] | undefined) ?? [];
    const afterAnswers = (change.proposed.answers as Answer[] | undefined) ?? [];
    return (
      <div className="ek-stack">
        <DiffView before={formatHtml(String(change.before.question_text ?? ""))} after={formatHtml(String(change.proposed.question_text ?? ""))}
          beforeTitle="Spørsmål nå" afterTitle="Foreslått spørsmål" />
        <div className="ek-grid" data-cols="2">
          <Answers answers={beforeAnswers} title="Svaralternativer nå" />
          <Answers answers={afterAnswers} title="Foreslåtte svaralternativer" />
        </div>
      </div>
    );
  }
  if (change.kind === "front_page.set") {
    const previousView = change.before.default_view;
    return (
      <KeyValue items={[
        ["Ny forside", change.target.title ?? change.target.object_id ?? "–"],
        ["Nåværende forside", change.before.front_page_url ? String(change.before.front_page_url) : "Ingen"],
        ["Startside for emnet", previousView === "wiki" ? "Forside (uendret)" : `${show(previousView)} → Forside`],
        ["Publisering", "Siden publiseres hvis den ikke er publisert"],
      ]} />
    );
  }
  const htmlField = HTML_FIELDS.find((f) => typeof change.proposed[f] === "string");
  if (htmlField) return <HtmlChange change={change} field={htmlField} />;
  if (change.kind === "blueprint.restrict") {
    const items = (change.proposed.items as { content_type: string; content_id: string; title?: string }[]) ?? [];
    return (
      <DataTable
        caption={`${change.proposed.restricted ? "Låses" : "Låses opp"}: ${items.length} ${items.length === 1 ? "element" : "elementer"}`}
        columns={[
          { key: "title", header: "Element", cell: (r) => r.title ?? r.content_id, rowHeader: true },
          { key: "type", header: "Type", cell: (r) => CONTENT_TYPE_LABELS[r.content_type] ?? r.content_type },
        ]}
        rows={items}
        rowKey={(r) => `${r.content_type}:${r.content_id}`}
      />
    );
  }
  const keys = Array.from(new Set([...Object.keys(change.proposed), ...Object.keys(change.before)])).filter((k) => !k.startsWith("_"));
  const fieldLabel = (k: string) => FIELD_LABELS[k] ?? (keys.length === 1 && change.target.title ? String(change.target.title) : k);
  return (
    <DataTable
      caption="Endrede verdier"
      columns={[
        { key: "field", header: "Felt", cell: (k: string) => fieldLabel(k), rowHeader: true },
        { key: "before", header: "Nå", cell: (k: string) => show(change.before[k]) },
        { key: "after", header: "Foreslått", cell: (k: string) => (k in change.proposed ? show(change.proposed[k]) : "Uendret") },
      ]}
      rows={keys}
      rowKey={(k) => k}
    />
  );
}

// Emne-RAG → Eksport: the index as a ZIP for other RAG tools, or as a readable document (Word, PDF, Markdown, text).
import { Download } from "lucide-react";

import { Alert, Card } from "../../../design-system";
import type { RagStatus } from "./api";

const FORMATS = [
  { format: "zip", label: "ZIP for andre RAG-verktøy",
    description: "Utdragene som JSONL med all metadata og vektorene, pluss manifest med modell og versjoner." },
  { format: "docx", label: "Word (.docx)",
    description: "Hele kunnskapsbasen som et dokument med overskrifter, tabeller og kilder – for Copilot, NotebookLM o.l." },
  { format: "pdf", label: "PDF",
    description: "Samme innhold som Word-dokumentet, klart til å lastes opp eller deles." },
  { format: "md", label: "Markdown (.md)", description: "Strukturert tekst som mange KI-verktøy leser godt." },
  { format: "txt", label: "Ren tekst (.txt)", description: "Uten formatering." },
];

export function ExportPanel({ courseId, status }: { courseId: string; status: RagStatus }) {
  if (!status.stats?.chunks) return <Alert tone="info">Opprett kunnskapsbasen først.</Alert>;
  return (
    <Card title="Eksporter kunnskapsbasen" headingLevel={2}>
      <div className="ek-stack" data-gap="4">
        <p className="ek-small">
          Eksporten inneholder bare det som er i kunnskapsbasen: lærerens innhold. Bildebeskrivelser og kontekstsetninger er
          merket som KI-generert. Vurder hvem du deler filene med – de kan inneholde upublisert innhold hvis du tok det med.
        </p>
        <ul className="ek-list-reset ek-stack" data-gap="3">
          {FORMATS.map((f) => (
            <li key={f.format} className="ek-card ek-card--compact">
              <div className="ek-cluster" data-justify="between">
                <span className="ek-stack" data-gap="1">
                  <strong>{f.label}</strong>
                  <span className="ek-small ek-muted">{f.description}</span>
                </span>
                <a className="ek-btn ek-btn--sm" href={`/api/courses/${courseId}/rag/export?format=${f.format}`} download>
                  <Download aria-hidden="true" />
                  Last ned{" "}<span className="ek-visually-hidden">{f.label}</span>
                </a>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

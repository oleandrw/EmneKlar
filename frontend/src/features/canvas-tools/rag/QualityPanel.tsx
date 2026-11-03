// Emne-RAG → Kvalitet: retrieval health (recall@5, MRR) from test questions, and how each question did.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Gauge, Play } from "lucide-react";
import { useState } from "react";

import { api } from "../../../core/api/client";
import { formatDateTime } from "../../../core/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  KeyFigure,
  KeyFigureList,
  type Column,
  type Tone,
} from "../../../design-system";
import { JobRunner } from "../../analysis/JobRunner";
import type { JobWording } from "../../analysis/ProgressPanel";
import type { Evaluation, RagStatus } from "./api";

const WORDING: JobWording = {
  noun: "evalueringen",
  current: "Nå",
  findingsTitle: "Resultat",
  findingsEmpty: "Resultatet vises når evalueringen er ferdig.",
  cancelNote: "Den forrige evalueringen beholdes.",
  countOnly: "spørsmål",
};

const HEALTH_TONE: Record<string, Tone> = { God: "success", Middels: "warning", Svak: "danger" };

function isEvaluation(value: unknown): value is Evaluation {
  return Boolean(value && typeof value === "object" && "health" in value);
}

export function QualityPanel({ courseId, status }: { courseId: string; status: RagStatus }) {
  const client = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [useAi, setUseAi] = useState(false);
  const [consent, setConsent] = useState(false);
  const run = useMutation({
    mutationFn: () => api.post<{ id: string }>(`/api/courses/${courseId}/rag/evaluate`, { use_ai: useAi, confirmed: consent }),
    onSuccess: (job) => setJobId(job.id),
  });
  const evaluation = status.index?.evaluation;
  if (!status.stats?.chunks) return <Alert tone="info">Bygg indeksen først. Evalueringen kjøres automatisk etterpå.</Alert>;
  const columns: Column<Evaluation["questions"][number]>[] = [
    { key: "question", header: "Testspørsmål", rowHeader: true, cell: (q) => q.question },
    { key: "source", header: "Laget fra", cell: (q) => q.citation },
    { key: "rank", header: "Funnet på plass", numeric: true, cell: (q) => q.rank ?? <Badge tone="danger">Ikke funnet</Badge> },
  ];
  return (
    <div className="ek-stack" data-gap="6">
      {isEvaluation(evaluation) ? (
        <Card title="Helsescore for søket" headingLevel={2}
          actions={<Badge tone={HEALTH_TONE[evaluation.health_label] ?? "neutral"}>{evaluation.health_label}</Badge>}>
          <div className="ek-stack" data-gap="4">
            <KeyFigureList label="Måletall">
              <KeyFigure icon={<Gauge />} tone={HEALTH_TONE[evaluation.health_label] ?? "neutral"} value={evaluation.health}
                label="av 100" description="Gjennomsnitt av recall@5 og MRR" />
              <KeyFigure icon={<Gauge />} tone="info" value={Math.round(evaluation.recall_at_5 * 100)} label="% recall@5"
                description="Riktig utdrag blant de fem beste treffene" />
              <KeyFigure icon={<Gauge />} tone="violet" value={Math.round(evaluation.mrr * 100)} label="% MRR"
                description="Hvor høyt riktig utdrag rangeres (1/plass)" />
            </KeyFigureList>
            <p className="ek-small">
              {evaluation.method_label}, {evaluation.questions.length} spørsmål. Målt {formatDateTime(evaluation.created_at)}.
            </p>
            <Alert tone="info">{evaluation.explanation}</Alert>
            <DataTable caption="Testspørsmål og resultat" columns={columns} rows={evaluation.questions}
              rowKey={(q) => `${q.chunk_id}-${q.question}`} />
          </div>
        </Card>
      ) : (
        <Alert tone="info">Det finnes ingen evaluering ennå.</Alert>
      )}
      <Card title="Kjør evaluering på nytt" headingLevel={2}>
        {jobId ? (
          <JobRunner jobId={jobId} wording={WORDING} onDone={() => {
            setJobId(null);
            void client.invalidateQueries({ queryKey: ["rag", courseId] });
          }} />
        ) : (
          <div className="ek-stack" data-gap="4">
            <Checkbox label="La KI lage testspørsmålene" checked={useAi} disabled={!status.ai.available}
              onChange={(e) => setUseAi(e.target.checked)}
              hint={status.ai.available ? "Gir mer naturlige spørsmål. Utvalgte utdrag fra lærerens innhold sendes til KI."
                : `Uten KI lages spørsmålene av utdragenes mest særpregede ord. ${status.ai.reason ?? ""}`} />
            {useAi ? (
              <Checkbox label="Jeg godtar at utvalgte utdrag sendes til KI-leverandøren" checked={consent}
                onChange={(e) => setConsent(e.target.checked)} />
            ) : null}
            <div className="ek-cluster">
              <Button icon={<Play aria-hidden="true" />} onClick={() => run.mutate()} loading={run.isPending}
                disabled={Boolean(status.busy_job) || (useAi && !consent)}>
                Kjør evaluering
              </Button>
            </div>
            {run.error ? <Alert tone="danger" role="alert">{(run.error as Error).message}</Alert> : null}
          </div>
        )}
      </Card>
    </div>
  );
}

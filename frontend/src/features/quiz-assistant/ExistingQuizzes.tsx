// «Eksisterende quizer»: list Classic Quizzes, check one deterministically or with grounded AI, act on findings.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { AiConsent, AiNotConfigured, useAiConfigured, type AiPlan } from "../../core/ai";
import type { Finding } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { formatNumber } from "../../core/format";
import { CLASSIFICATION } from "../../core/labels";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  DataTable,
  EmptyState,
  ExternalLink,
  KeyValue,
  Spinner,
  type Column,
} from "../../design-system";
import { JobRunner } from "../analysis/JobRunner";
import type { JobWording } from "../analysis/ProgressPanel";
import { FindingDetail } from "../findings/FindingDetail";
import { prepareReview, startReview, useQuizDetail, useQuizzes, type QuizQuestion, type QuizSummary } from "./api";

const REVIEW_WORDING: JobWording = {
  noun: "kontrollen",
  current: "Nå kontrolleres",
  findingsTitle: "Funn så langt",
  findingsEmpty: "Ingen funn registrert ennå.",
  cancelNote: "Kontrollen stoppes. Funn fra tidligere kontroller beholdes.",
};
const QUIZ_TYPE: Record<string, string> = {
  practice_quiz: "Øvingsquiz", assignment: "Vurdert quiz", graded_survey: "Vurdert spørreundersøkelse",
  survey: "Spørreundersøkelse",
};

export function QuizList() {
  const { courseId } = useCurrentCourse();
  const quizzes = useQuizzes(courseId);
  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (quizzes.isPending) return <Spinner label="Henter quizer fra Canvas …" />;
  if (quizzes.error) {
    return <Alert tone="danger" role="alert" title="Kunne ikke hente quizene">{(quizzes.error as Error).message}</Alert>;
  }
  const columns: Column<QuizSummary>[] = [
    { key: "title", header: "Quiz", rowHeader: true, cell: (q) => <Link to={`quiz/${q.id}`}>{q.title}</Link> },
    { key: "type", header: "Type", cell: (q) => QUIZ_TYPE[q.quiz_type ?? ""] ?? q.quiz_type ?? "–" },
    { key: "questions", header: "Spørsmål", numeric: true, cell: (q) => q.question_count ?? "–" },
    { key: "points", header: "Poeng", numeric: true, cell: (q) => q.points_possible ?? "–" },
    { key: "published", header: "Status", cell: (q) => (q.published ? <Badge tone="success">Publisert</Badge> : <Badge>Upublisert</Badge>) },
    {
      key: "findings",
      header: "Åpne funn",
      numeric: true,
      cell: (q) => (q.open_findings ? <Badge tone="warning">{formatNumber(q.open_findings)}</Badge> : <span className="ek-muted">0</span>),
    },
  ];
  return (
    <div className="ek-stack">
      <p className="ek-small ek-muted">
        Klassiske quizer i emnet. Velg en quiz for å kontrollere spørsmål, svaralternativer og fasit. Nye quizer (New
        Quizzes) støttes ikke i denne versjonen.
      </p>
      <DataTable caption="Klassiske quizer" captionHidden columns={columns} rows={quizzes.data.quizzes} rowKey={(q) => q.id}
        empty="Emnet har ingen klassiske quizer." />
    </div>
  );
}

function QuestionCard({ question, findings, onOpen }: { question: QuizQuestion; findings: Finding[]; onOpen: (f: Finding) => void }) {
  return (
    <li className="ek-question">
      <div className="ek-cluster" data-justify="between" data-align="start">
        <div className="ek-stack" data-gap="1" style={{ flex: 1, minWidth: "16rem" }}>
          <span className="ek-xs ek-muted">
            Spørsmål {question.position} · {question.type_label} · {question.points} poeng
            {question.group_id ? " · i gruppe" : ""}
          </span>
          <p className="ek-strong">{question.text || <em>(tom spørsmålstekst)</em>}</p>
          {question.answers.length ? (
            <ul className="ek-answers" aria-label="Svaralternativer">
              {question.answers.map((a, i) => (
                <li key={a.id ?? i}>
                  {a.correct ? (
                    <Badge tone="success" icon={<Check aria-hidden="true" size={14} />}>Riktig</Badge>
                  ) : (
                    <Badge>Feil</Badge>
                  )}
                  <span>{a.text || <em>(tomt alternativ)</em>}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
      {findings.length ? (
        <ul className="ek-list-reset ek-stack ek-mt-2" data-gap="1" aria-label={`Funn for spørsmål ${question.position}`}>
          {findings.map((f) => (
            <li key={f.id} className="ek-cluster" data-gap="2">
              <Badge tone={CLASSIFICATION[f.classification].tone}>{CLASSIFICATION[f.classification].label}</Badge>
              {f.test_method === "ai" ? <Badge tone="violet" icon={<Sparkles aria-hidden="true" size={12} />}>KI</Badge> : null}
              <span className="ek-small">{f.title}</span>
              <Button size="sm" variant="link" onClick={() => onOpen(f)}>
                Vis<span className="ek-visually-hidden">: {f.title}</span>
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function QuizReview() {
  const { quizId = null } = useParams();
  const { courseId } = useCurrentCourse();
  const detail = useQuizDetail(courseId, quizId);
  const client = useQueryClient();
  const aiConfigured = useAiConfigured();
  const [jobId, setJobId] = useState<string | null>(null);
  const [plan, setPlan] = useState<AiPlan | null>(null);
  const [selected, setSelected] = useState<Finding | null>(null);
  const prepare = useMutation({ mutationFn: () => prepareReview(courseId!, quizId!), onSuccess: setPlan });
  const start = useMutation({
    mutationFn: (useAi: boolean) => startReview(courseId!, quizId!, { use_ai: useAi, confirmed: useAi }),
    onSuccess: (job) => {
      setPlan(null);
      setJobId(job.id);
    },
  });
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["quiz", courseId, quizId] });
    void client.invalidateQueries({ queryKey: ["quizzes", courseId] });
    void client.invalidateQueries({ queryKey: ["findings"] });
    void client.invalidateQueries({ queryKey: ["overview"] });
  };

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (detail.isPending) return <Spinner label="Henter quizen …" />;
  if (detail.error) {
    return <Alert tone="danger" role="alert" title="Kunne ikke hente quizen">{(detail.error as Error).message}</Alert>;
  }
  const { quiz, questions, findings } = detail.data;
  const quizLevel = findings.filter((f) => f.object_type === "quiz");
  const settings = quiz.settings;
  const running = jobId !== null;

  return (
    <div className="ek-stack" data-gap="6">
      <div>
        <ButtonLink to="/quizassistent" variant="link" icon={<ArrowLeft aria-hidden="true" />}>Alle quizer</ButtonLink>
      </div>
      <Card
        title={quiz.title}
        actions={quiz.html_url ? <ExternalLink href={quiz.html_url}>Åpne i Canvas</ExternalLink> : null}
      >
        <div className="ek-stack">
          <KeyValue
            items={[
              ["Type", QUIZ_TYPE[String(settings.quiz_type)] ?? String(settings.quiz_type ?? "–")],
              ["Spørsmål", String(questions.length)],
              ["Forsøk", settings.allowed_attempts === -1 ? "Ubegrenset" : String(settings.allowed_attempts ?? 1)],
              ["Bland svaralternativer", settings.shuffle_answers ? "Ja" : "Nei"],
              ["Tidsbegrensning", settings.time_limit ? `${String(settings.time_limit)} minutter` : "Ingen"],
              ["Status", settings.published ? "Publisert" : "Upublisert"],
            ]}
          />
          <div className="ek-cluster">
            <Button variant="primary" icon={<ShieldCheck aria-hidden="true" />} onClick={() => start.mutate(false)}
              loading={start.isPending && start.variables === false} disabled={running}>
              Kontroller quizen
            </Button>
            {aiConfigured ? (
              <Button icon={<Sparkles aria-hidden="true" />} onClick={() => prepare.mutate()} loading={prepare.isPending}
                disabled={running}>
                KI-vurdering mot emnets innhold
              </Button>
            ) : null}
          </div>
          {!aiConfigured ? <AiNotConfigured what="KI-vurdering av fasit og formulering" /> : null}
          <p className="ek-xs ek-muted">
            Kontrollen leser bare fra Canvas. KI-vurderingen sammenligner spørsmålene med teksten i emnet og må alltid
            vurderes av deg – EmneKlar endrer aldri en fasit automatisk.
          </p>
          {plan ? (
            <AiConsent plan={plan} onCancel={() => setPlan(null)} onConfirm={() => start.mutate(true)}
              loading={start.isPending} confirmLabel="Send og vurder" />
          ) : null}
          {start.error || prepare.error ? (
            <Alert tone="danger" role="alert" title="Kunne ikke starte kontrollen">
              {((start.error ?? prepare.error) as Error).message}
            </Alert>
          ) : null}
          {jobId ? (
            <JobRunner jobId={jobId} wording={REVIEW_WORDING} onDone={() => {
              refresh();
              setJobId(null);
            }} />
          ) : null}
        </div>
      </Card>

      {quiz.groups.some((g) => g.assessment_question_bank_id) ? (
        <Alert tone="info" title="Spørsmål fra spørsmålsbank">
          Quizen trekker spørsmål fra en spørsmålsbank i Canvas. Canvas-API-et gir ikke tilgang til disse spørsmålene via
          quizen, så de er ikke kontrollert.
        </Alert>
      ) : null}

      {quizLevel.length ? (
        <section className="ek-stack" data-gap="2" aria-labelledby="quizfunn">
          <h2 id="quizfunn">Gjelder hele quizen</h2>
          <ul className="ek-list-reset ek-stack" data-gap="1">
            {quizLevel.map((f) => (
              <li key={f.id} className="ek-cluster" data-gap="2">
                <Badge tone={CLASSIFICATION[f.classification].tone}>{CLASSIFICATION[f.classification].label}</Badge>
                <span className="ek-small">{f.message}</span>
                <Button size="sm" variant="link" onClick={() => setSelected(f)}>Vis</Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="ek-stack" aria-labelledby="sporsmal">
        <div className="ek-section__header">
          <h2 id="sporsmal">Spørsmål</h2>
          <span className="ek-small ek-muted">{findings.length} åpne funn</span>
        </div>
        {questions.length ? (
          <ol className="ek-list-reset ek-stack" data-gap="2">
            {questions.map((q) => (
              <QuestionCard key={q.id} question={q} findings={findings.filter((f) => f.object_id === q.id)} onOpen={setSelected} />
            ))}
          </ol>
        ) : (
          <EmptyState title="Quizen har ingen spørsmål" headingLevel={3} />
        )}
      </section>
      <FindingDetail finding={selected} open={selected !== null} onClose={() => {
        setSelected(null);
        refresh();
      }} />
    </div>
  );
}

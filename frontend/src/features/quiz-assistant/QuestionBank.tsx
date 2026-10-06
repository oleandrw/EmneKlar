// «KI-spørsmålsbank»: EmneKlar's own question workspace. Generate (grounded), review, edit and approve questions.
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Pencil, Plus, Sparkles, Trash, X } from "lucide-react";
import { useState } from "react";

import { AiConsent, AiNotConfigured, useAiConfigured, type AiPlan } from "../../core/ai";
import { api } from "../../core/api/client";
import type { Job } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { formatNumber } from "../../core/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  DataTable,
  Dialog,
  EmptyState,
  Fieldset,
  IconButton,
  SelectField,
  Spinner,
  TextArea,
  TextField,
  useToast,
  type Column,
  type Tone,
} from "../../design-system";
import { JobRunner } from "../analysis/JobRunner";
import type { JobWording } from "../analysis/ProgressPanel";
import {
  COVERAGE_LEVEL,
  DIFFICULTY,
  QUESTION_TYPES,
  REVIEW_STATUS,
  useBank,
  useBankMutations,
  useCoverage,
  type BankFilters,
  type BankItem,
  type Coverage,
  type QuestionType,
  type QuizAnswer,
} from "./api";

const GENERATE_WORDING: JobWording = {
  noun: "genereringen",
  current: "Nå behandles",
  findingsTitle: "Spørsmål beholdt så langt",
  findingsEmpty: "Ingen spørsmål ennå.",
  cancelNote: "Spørsmål som allerede er laget, beholdes i spørsmålsbanken som utkast.",
  countOnly: "spørsmål med bekreftet kilde",
};

interface StructureModules {
  snapshot_at: string | null;
  modules: { id: string; name: string }[];
}

function useModules(courseId: string | null) {
  return useQuery({
    queryKey: ["structure", courseId],
    queryFn: () => api.get<StructureModules>(`/api/courses/${courseId}/structure`),
    enabled: Boolean(courseId),
  });
}

/* ---------------------------------------------------------------------------- editor dialog */

const EMPTY_ANSWERS: QuizAnswer[] = [
  { text: "", correct: true },
  { text: "", correct: false },
  { text: "", correct: false },
];

function BankItemDialog({
  open,
  item,
  modules,
  onClose,
}: {
  open: boolean;
  item: BankItem | null;
  modules: { id: string; name: string }[];
  onClose: () => void;
}) {
  const { courseId } = useCurrentCourse();
  const m = useBankMutations(courseId);
  const [type, setType] = useState<QuestionType>(item?.question_type ?? "single_choice");
  const [stem, setStem] = useState(item?.stem ?? "");
  const [answers, setAnswers] = useState<QuizAnswer[]>(item?.answers ?? EMPTY_ANSWERS);
  const [explanation, setExplanation] = useState(item?.explanation ?? "");
  const [moduleName, setModuleName] = useState(item?.module_name ?? "");
  const [topic, setTopic] = useState(item?.topic ?? "");
  const [difficulty, setDifficulty] = useState<string>(item?.difficulty ?? "medium");
  const mutation = item ? m.update : m.create;
  const saving = m.update.isPending || m.create.isPending;

  const setTypeAndAnswers = (value: QuestionType) => {
    setType(value);
    if (value === "true_false") setAnswers([{ text: "Sant", correct: true }, { text: "Usant", correct: false }]);
  };
  const save = () => {
    const body = {
      question_type: type, stem, answers: answers.filter((a) => a.text.trim()), explanation,
      module_name: moduleName || null, module_id: modules.find((x) => x.name === moduleName)?.id ?? null, topic,
      difficulty: difficulty as BankItem["difficulty"],
    };
    if (item) m.update.mutate({ id: item.id, ...body }, { onSuccess: onClose });
    else m.create.mutate(body, { onSuccess: onClose });
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={item ? "Rediger spørsmål" : "Nytt spørsmål"}
      description="Spørsmål du skriver selv merkes som ikke kontrollert mot emnets innhold."
      footer={
        <>
          <Button onClick={onClose}>Avbryt</Button>
          <Button variant="primary" onClick={save} loading={saving}>
            Lagre
          </Button>
        </>
      }
    >
      <div className="ek-stack">
        <SelectField label="Spørsmålstype" value={type} onChange={(e) => setTypeAndAnswers(e.target.value as QuestionType)}
          options={QUESTION_TYPES} />
        <TextArea label="Spørsmål" value={stem} onChange={(e) => setStem(e.target.value)} rows={3} maxLength={4000} />
        <Fieldset legend="Svaralternativer" hint="Merk av riktig svar. Enkeltvalg og flere svar trenger minst tre alternativer.">
          {answers.map((a, i) => (
            <div key={i} className="ek-cluster" data-align="end">
              <div style={{ flex: 1, minWidth: "12rem" }}>
                <TextField label={`Alternativ ${i + 1}`} value={a.text} maxLength={1000} disabled={type === "true_false"}
                  onChange={(e) => setAnswers(answers.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
              </div>
              <Checkbox label="Riktig" checked={a.correct}
                onChange={(e) =>
                  setAnswers(answers.map((x, j) =>
                    type === "multiple_answers"
                      ? (j === i ? { ...x, correct: e.target.checked } : x)
                      : { ...x, correct: j === i ? e.target.checked : false }))
                } />
              {type !== "true_false" ? (
                <IconButton label={`Fjern alternativ ${i + 1}`} onClick={() => setAnswers(answers.filter((_, j) => j !== i))}
                  disabled={answers.length <= 2}>
                  <Trash aria-hidden="true" size={16} />
                </IconButton>
              ) : null}
            </div>
          ))}
          {type !== "true_false" ? (
            <div>
              <Button size="sm" icon={<Plus aria-hidden="true" />} disabled={answers.length >= 10}
                onClick={() => setAnswers([...answers, { text: "", correct: false }])}>
                Legg til alternativ
              </Button>
            </div>
          ) : null}
        </Fieldset>
        <TextArea label="Forklaring" optional hint="Vises for studentene etter innlevering (nøytral kommentar)."
          value={explanation} onChange={(e) => setExplanation(e.target.value)} rows={2} maxLength={4000} />
        <div className="ek-grid" data-cols="2">
          <SelectField label="Modul" value={moduleName} onChange={(e) => setModuleName(e.target.value)} placeholder="Ingen modul"
            options={modules.map((x) => ({ value: x.name, label: x.name }))} />
          <TextField label="Tema" optional value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={300} />
          <SelectField label="Vanskelighetsgrad" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}
            options={Object.entries(DIFFICULTY).map(([value, label]) => ({ value, label }))} />
        </div>
        {mutation.error ? (
          <Alert tone="danger" role="alert" title="Kunne ikke lagre">
            {(mutation.error as Error).message}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}

/* --------------------------------------------------------------------------------- generation */

function GeneratePanel({ modules, hasSnapshot, onClose }: { modules: { id: string; name: string }[]; hasSnapshot: boolean; onClose: () => void }) {
  const { courseId } = useCurrentCourse();
  const toast = useToast();
  const m = useBankMutations(courseId);
  const [selected, setSelected] = useState<string[]>([]);
  const [count, setCount] = useState("20");
  const [types, setTypes] = useState<QuestionType[]>(["single_choice", "multiple_answers", "true_false"]);
  const [plan, setPlan] = useState<(AiPlan & { chunks?: number; pages?: number }) | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const body = { module_ids: selected, count: Math.max(1, Math.min(60, Number(count) || 1)), types };
  const prepare = useMutation({
    mutationFn: () => api.post<AiPlan & { chunks?: number; pages?: number }>(`/api/courses/${courseId}/bank/generate/prepare`, body),
    onSuccess: setPlan,
  });
  const start = useMutation({
    mutationFn: () => api.post<Job>(`/api/courses/${courseId}/bank/generate`, { ...body, confirmed: true }),
    onSuccess: (job) => {
      setPlan(null);
      setJobId(job.id);
    },
  });

  if (!hasSnapshot) {
    return (
      <Alert tone="info" title="Kjør en analyse først">
        Spørsmål lages bare fra innholdet i emnet. Kjør en analyse, så EmneKlar har oppdatert innhold å bygge på.
      </Alert>
    );
  }
  return (
    <Card title="Lag spørsmål med KI" headingLevel={3} actions={<IconButton label="Lukk" onClick={onClose}><X aria-hidden="true" /></IconButton>}>
      <div className="ek-stack">
        <p className="ek-small">
          KI lager spørsmål bare fra tekst i emnet. Hvert spørsmål må ha et ordrett sitat fra kilden – spørsmål uten
          bekreftet kilde forkastes. Alle spørsmål havner som utkast til vurdering. Lag gjerne flere enn du trenger, og
          godkjenn de beste.
        </p>
        <Fieldset legend="Kilder" hint="Velg ingen for å bruke hele emnet.">
          {modules.map((x) => (
            <Checkbox key={x.id} label={x.name} checked={selected.includes(x.id)}
              onChange={(e) => setSelected(e.target.checked ? [...selected, x.id] : selected.filter((id) => id !== x.id))} />
          ))}
        </Fieldset>
        <div className="ek-grid" data-cols="2">
          <TextField label="Antall spørsmål" type="number" min={1} max={60} value={count} onChange={(e) => setCount(e.target.value)}
            hint="Inntil 60 om gangen." />
          <Fieldset legend="Spørsmålstyper">
            {QUESTION_TYPES.map((t) => (
              <Checkbox key={t.value} label={t.label} checked={types.includes(t.value)}
                onChange={(e) => setTypes(e.target.checked ? [...types, t.value] : types.filter((x) => x !== t.value))} />
            ))}
          </Fieldset>
        </div>
        {!plan && !jobId ? (
          <div>
            <Button variant="primary" icon={<Sparkles aria-hidden="true" />} onClick={() => prepare.mutate()}
              loading={prepare.isPending} disabled={types.length === 0}>
              Forbered generering
            </Button>
          </div>
        ) : null}
        {plan ? (
          <AiConsent plan={plan} onCancel={() => setPlan(null)} onConfirm={() => start.mutate()} loading={start.isPending}
            confirmLabel="Send og lag spørsmål" />
        ) : null}
        {prepare.error || start.error ? (
          <Alert tone="danger" role="alert" title="Kunne ikke starte">
            {((prepare.error ?? start.error) as Error).message}
          </Alert>
        ) : null}
        {jobId ? (
          <JobRunner jobId={jobId} wording={GENERATE_WORDING} onDone={(job) => {
            m.refresh();
            const r = job.result as { kept?: number; discarded_unverified?: number; duplicates?: number } | null;
            if (job.status === "completed" && r) {
              toast.show({
                tone: "success",
                title: `${r.kept ?? 0} nye spørsmål til vurdering`,
                body: `${r.discarded_unverified ?? 0} forkastet uten bekreftet kilde, ${r.duplicates ?? 0} duplikater.`,
              });
            }
          }} />
        ) : null}
      </div>
    </Card>
  );
}

/* ----------------------------------------------------------------------------------- coverage */

function CoverageTable({ coverage }: { coverage: Coverage }) {
  const columns: Column<Coverage["modules"][number]>[] = [
    { key: "module", header: "Modul", rowHeader: true, cell: (r) => r.module },
    { key: "approved", header: "Godkjent", numeric: true, cell: (r) => r.approved },
    { key: "draft", header: "Til vurdering", numeric: true, cell: (r) => r.draft },
    { key: "words", header: "Ord i kildene", numeric: true, cell: (r) => formatNumber(r.words) },
    {
      key: "level",
      header: "Dekning",
      cell: (r) => <Badge tone={COVERAGE_LEVEL[r.level]?.tone ?? "neutral"}>{COVERAGE_LEVEL[r.level]?.label ?? r.level}</Badge>,
    },
  ];
  return (
    <DataTable caption="Dekning per modul (godkjente spørsmål sett mot mengden tekst)" columns={columns}
      rows={coverage.modules} rowKey={(r) => r.module} empty="Ingen moduler å vise." />
  );
}

/* --------------------------------------------------------------------------------------- page */

const GROUNDING: Record<BankItem["grounding"], { label: string; tone: Tone }> = {
  verified: { label: "Kilde bekreftet", tone: "teal" },
  partial: { label: "Endret etter kildekontroll", tone: "warning" },
  unverified: { label: "Ikke kontrollert mot emnet", tone: "warning" },
};

/** Short form of a question for accessible button names («Godkjenn: Hva er …»). */
const shortStem = (stem: string) => (stem.length > 60 ? `${stem.slice(0, 57)}…` : stem);

function BankItemCard({ item, onEdit, onDelete }: { item: BankItem; onEdit: () => void; onDelete: () => void }) {
  const { courseId } = useCurrentCourse();
  const m = useBankMutations(courseId);
  const status = REVIEW_STATUS[item.review_status];
  const grounding = GROUNDING[item.grounding] ?? GROUNDING.unverified;
  const name = shortStem(item.stem);
  return (
    <li className="ek-question">
      <div className="ek-stack" data-gap="2">
        <div className="ek-cluster" data-gap="2">
          <Badge tone={status.tone}>{status.label}</Badge>
          <Badge>{item.type_label}</Badge>
          <Badge>{DIFFICULTY[item.difficulty]}</Badge>
          {item.origin === "ai" ? (
            <Badge tone="violet" icon={<Sparkles aria-hidden="true" size={12} />}>KI-forslag – må vurderes</Badge>
          ) : (
            <Badge>Skrevet manuelt</Badge>
          )}
          <Badge tone={grounding.tone}>{grounding.label}</Badge>
          {item.used_in.length ? <Badge tone="info">Brukt i {item.used_in.map((u) => u.title).join(", ")}</Badge> : null}
        </div>
        <p className="ek-strong">{item.stem}</p>
        <ul className="ek-answers" aria-label="Svaralternativer">
          {item.answers.map((a, i) => (
            <li key={i}>
              {a.correct ? <Badge tone="success" icon={<Check aria-hidden="true" size={14} />}>Riktig</Badge> : <Badge>Feil</Badge>}
              <span>{a.text}</span>
            </li>
          ))}
        </ul>
        {item.explanation ? <p className="ek-small ek-muted">Forklaring: {item.explanation}</p> : null}
        {item.sources.map((s) => (
          <div key={s.chunk_id} className="ek-stack" data-gap="1">
            <blockquote className="ek-quote">«{s.quote}»</blockquote>
            <span className="ek-xs ek-muted">Kilde: {s.title}</span>
          </div>
        ))}
        <p className="ek-xs ek-muted">
          {item.module_name ?? "Uten modul"}
          {item.topic ? ` · ${item.topic}` : ""}
          {item.generator.model ? ` · laget med ${item.generator.model}` : ""}
        </p>
        <div className="ek-cluster" data-gap="2">
          {item.review_status !== "approved" ? (
            <Button size="sm" variant="primary" icon={<Check aria-hidden="true" />} loading={m.update.isPending}
              aria-label={`Godkjenn: ${name}`} onClick={() => m.update.mutate({ id: item.id, review_status: "approved" })}>
              Godkjenn
            </Button>
          ) : null}
          {item.review_status !== "rejected" ? (
            <Button size="sm" aria-label={`Avvis: ${name}`}
              onClick={() => m.update.mutate({ id: item.id, review_status: "rejected" })}>Avvis</Button>
          ) : null}
          <Button size="sm" icon={<Pencil aria-hidden="true" />} onClick={onEdit} aria-label={`Rediger: ${name}`}>Rediger</Button>
          <Button size="sm" variant="ghost" icon={<Trash aria-hidden="true" />} onClick={onDelete} aria-label={`Slett: ${name}`}>
            Slett
          </Button>
        </div>
        {m.update.error ? <Alert tone="danger" role="alert">{(m.update.error as Error).message}</Alert> : null}
      </div>
    </li>
  );
}

export function QuestionBank() {
  const { courseId } = useCurrentCourse();
  const aiConfigured = useAiConfigured();
  const [filters, setFilters] = useState<BankFilters>({ status: "", module: "", q: "" });
  const bank = useBank(courseId, filters);
  const coverage = useCoverage(courseId);
  const modules = useModules(courseId);
  const m = useBankMutations(courseId);
  const [editing, setEditing] = useState<BankItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<BankItem | null>(null);
  const [generating, setGenerating] = useState(false);

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  const moduleList = modules.data?.modules ?? [];

  return (
    <div className="ek-stack" data-gap="6">
      <p className="ek-small ek-muted">
        KI-spørsmålsbanken er EmneKlars eget arbeidsområde – ikke spørsmålsbankene i Canvas. Bare godkjente spørsmål kan
        brukes når du lager en quiz.
      </p>
      <div className="ek-cluster">
        {aiConfigured ? (
          <Button variant="primary" icon={<Sparkles aria-hidden="true" />} onClick={() => setGenerating(true)} disabled={generating}>
            Lag spørsmål med KI
          </Button>
        ) : null}
        <Button icon={<Plus aria-hidden="true" />} onClick={() => setCreating(true)}>Nytt spørsmål</Button>
      </div>
      {!aiConfigured ? <AiNotConfigured what="Å lage spørsmål med KI" /> : null}
      {generating ? (
        <GeneratePanel modules={moduleList} hasSnapshot={Boolean(modules.data?.snapshot_at)} onClose={() => setGenerating(false)} />
      ) : null}

      <Card title="Spørsmål" headingLevel={2}>
        <div className="ek-stack">
          <div className="ek-cluster" data-align="end">
            <div style={{ minWidth: "12rem" }}>
              <SelectField label="Status" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                placeholder="Alle" options={Object.entries(REVIEW_STATUS).map(([value, s]) => ({ value, label: s.label }))} />
            </div>
            <div style={{ minWidth: "14rem" }}>
              <SelectField label="Modul" value={filters.module} onChange={(e) => setFilters({ ...filters, module: e.target.value })}
                placeholder="Alle moduler" options={moduleList.map((x) => ({ value: x.name, label: x.name }))} />
            </div>
            <div style={{ flex: 1, minWidth: "14rem" }}>
              <TextField label="Søk" type="search" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
            </div>
          </div>
          {bank.isPending ? <Spinner label="Henter spørsmål …" /> : null}
          {bank.error ? <Alert tone="danger" role="alert">{(bank.error as Error).message}</Alert> : null}
          {bank.data ? (
            <>
              <p className="ek-small" aria-live="polite">
                {bank.data.items.length} spørsmål · {bank.data.counts.approved} godkjent · {bank.data.counts.draft} til vurdering
                · {bank.data.counts.rejected} avvist
              </p>
              {bank.data.items.length ? (
                <ul className="ek-list-reset ek-stack" data-gap="2">
                  {bank.data.items.map((item) => (
                    <BankItemCard key={item.id} item={item} onEdit={() => setEditing(item)} onDelete={() => setDeleting(item)} />
                  ))}
                </ul>
              ) : (
                <EmptyState title="Ingen spørsmål" headingLevel={3}>
                  Lag spørsmål med KI fra emnets innhold, eller skriv dem selv.
                </EmptyState>
              )}
            </>
          ) : null}
        </div>
      </Card>

      {coverage.data && coverage.data.modules.length ? (
        <Card title="Dekning av emnet" headingLevel={2}>
          <CoverageTable coverage={coverage.data} />
        </Card>
      ) : null}

      {creating ? <BankItemDialog open item={null} modules={moduleList} onClose={() => setCreating(false)} /> : null}
      {editing ? <BankItemDialog key={editing.id} open item={editing} modules={moduleList} onClose={() => setEditing(null)} /> : null}
      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && m.remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        title="Slette spørsmålet?"
        confirmLabel="Slett spørsmålet"
        danger
        loading={m.remove.isPending}
      >
        <p>Spørsmålet slettes fra KI-spørsmålsbanken i EmneKlar. Quizer som allerede er laget i Canvas, påvirkes ikke.</p>
      </ConfirmDialog>
    </div>
  );
}

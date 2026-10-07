// Suggested fixes for a finding. Every path ends in the change queue – nothing writes to Canvas directly.
//   HTML fixes (UU, innholdskvalitet): «Forhåndsvis løsning» → diff + preview → «Legg endring til kø»
//   Structure suggestions: «Forhåndsvis» → «Godkjenn forslag» (or «Avvis» = ignore)
//   Quiz suggestions: «Godkjenn forslag» / «Rediger» (or «Behold» = ignore)
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Plus, Trash } from "lucide-react";
import { useState } from "react";

import { AiBadge } from "../../core/ai";
import { api } from "../../core/api/client";
import type { Finding } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { RISK } from "../../core/labels";
import { useSession } from "../../core/session";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  DiffView,
  Fieldset,
  HtmlPreview,
  IconButton,
  KeyValue,
  SelectField,
  TextArea,
  TextField,
  useToast,
  type PreviewDevice,
} from "../../design-system";
import { AltTextSuggestion } from "./AltTextSuggestion";
import { fixPreview, fixStage, useFindingActions, type FixParams, type FixPreview } from "./api";

const LANGS = [
  { value: "en", label: "Engelsk (en)" },
  { value: "nb", label: "Norsk bokmål (nb)" },
  { value: "nn", label: "Norsk nynorsk (nn)" },
  { value: "se", label: "Nordsamisk (se)" },
  { value: "sv", label: "Svensk (sv)" },
  { value: "da", label: "Dansk (da)" },
  { value: "de", label: "Tysk (de)" },
  { value: "fr", label: "Fransk (fr)" },
  { value: "es", label: "Spansk (es)" },
];

export function FixPanel({ finding, onStaged }: { finding: Finding; onStaged: () => void }) {
  if (finding.domain === "structure") return <StructureFixPanel finding={finding} onStaged={onStaged} />;
  if (finding.fix?.type === "quiz_question_update") return <QuizFixPanel finding={finding} onStaged={onStaged} />;
  return <HtmlFixPanel finding={finding} onStaged={onStaged} />;
}

function useStagedToast() {
  const session = useSession();
  const toast = useToast();
  const actions = useFindingActions();
  return () => {
    actions.refresh();
    toast.show({
      tone: "success",
      title: "Endringen er lagt i endringskøen",
      body: session.dry_run
        ? "Dry run er på – endringen sendes ikke til Canvas før du slår det av."
        : "Godkjenn og gjennomfør den fra endringskøen.",
    });
  };
}

/* ----------------------------------------------------------------------------- HTML fixes */

function HtmlFixPanel({ finding, onStaged }: { finding: Finding; onStaged: () => void }) {
  const fix = finding.fix!;
  const staged = useStagedToast();
  const fixParams = (fix.params ?? {}) as Record<string, unknown>;
  const [text, setText] = useState<string>(String(fixParams.suggestion ?? ""));
  const [decorative, setDecorative] = useState(false);
  const [level, setLevel] = useState<string>(String(fixParams.level ?? 2));
  const [lang, setLang] = useState<string>(String(fixParams.lang ?? "en"));
  const [url, setUrl] = useState<string>(String(fixParams.suggestion ?? ""));
  const [unlink, setUnlink] = useState(false);
  const [options, setOptions] = useState<string[] | null>(null);
  const [device, setDevice] = useState<PreviewDevice>("desktop");
  const [previewed, setPreviewed] = useState<{ key: string; data: FixPreview } | null>(null);

  const cleanupOptions = useQuery({
    queryKey: ["cleanup-options"],
    queryFn: () => api.get<{ options: { id: string; label: string }[] }>("/api/content-quality/cleanup-options"),
    enabled: fix.type === "cleanup",
    staleTime: Infinity,
  });
  const chosen = options ?? cleanupOptions.data?.options.map((o) => o.id) ?? [];

  const needsText = ["set_alt", "set_link_text", "set_iframe_title", "table_caption"].includes(fix.type);
  const needsLevel = ["change_heading_level", "convert_to_heading"].includes(fix.type);
  const params: FixParams = {
    text: needsText && !decorative ? text : undefined,
    decorative: fix.type === "set_alt" ? decorative : undefined,
    level: needsLevel ? Number(level) : undefined,
    lang: fix.type === "set_lang" ? lang : undefined,
    url: fix.type === "replace_link_href" && !unlink ? url : undefined,
    unlink: fix.type === "replace_link_href" ? unlink : undefined,
    options: fix.type === "cleanup" ? chosen : undefined,
  };
  const textLabel: Record<string, string> = {
    set_alt: "Alternativ tekst",
    set_link_text: "Lenketekst",
    set_iframe_title: "Tittel på innebygd innhold",
    table_caption: "Tabelltittel",
  };
  // The preview belongs to exactly these choices; any change (text, language, AI suggestion …) requires a new one.
  const key = JSON.stringify(params);
  const preview = previewed?.key === key ? previewed.data : null;

  const previewMutation = useMutation({
    // The key travels with the request, so a slow answer is never shown as the preview of newer choices.
    mutationFn: async (request: { key: string; params: FixParams }) =>
      ({ key: request.key, data: await fixPreview(finding.id, request.params) }),
    onSuccess: setPreviewed,
  });
  const stageMutation = useMutation({
    mutationFn: () => fixStage(finding.id, params),
    onSuccess: () => {
      staged();
      onStaged();
    },
  });

  return (
    <div className="ek-stack">
      <h3>{fix.label}</h3>
      {fix.type === "set_alt" ? (
        <Checkbox
          label="Bildet er dekorativt (tom alt-tekst)"
          hint="Velg dette bare når bildet ikke formidler noe som ikke står i teksten."
          checked={decorative}
          onChange={(e) => {
            setDecorative(e.target.checked);
          }}
        />
      ) : null}
      {needsText && !decorative ? (
        <>
          <TextField
            label={textLabel[fix.type] ?? "Tekst"}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            hint={fix.type === "set_alt" ? "Beskriv det bildet formidler i denne sammenhengen – ikke utseendet alene." : undefined}
            maxLength={500}
          />
          {fix.type === "set_alt" ? <AltTextSuggestion finding={finding} onUse={(v) => setText(v)} /> : null}
        </>
      ) : null}
      {needsLevel ? (
        <SelectField
          label="Overskriftsnivå"
          value={level}
          onChange={(e) => {
            setLevel(e.target.value);
          }}
          options={[2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `Overskrift ${n}` }))}
        />
      ) : null}
      {fix.type === "set_lang" ? (
        <SelectField label="Språk" value={lang} onChange={(e) => setLang(e.target.value)} options={LANGS} />
      ) : null}
      {fix.type === "replace_link_href" ? (
        <>
          {!unlink ? (
            <TextField
              label="Ny adresse"
              type="url"
              value={url}
              placeholder="https://"
              hint="EmneKlar sletter aldri lenker automatisk. Kontroller at den nye adressen er riktig."
              onChange={(e) => {
                setUrl(e.target.value);
              }}
            />
          ) : null}
          {fixParams.allow_unlink ? (
            <Checkbox
              label={`Fjern lenken, men behold teksten${fixParams.text ? ` «${String(fixParams.text)}»` : ""}`}
              checked={unlink}
              onChange={(e) => {
                setUnlink(e.target.checked);
              }}
            />
          ) : null}
        </>
      ) : null}
      {fix.type === "cleanup" && cleanupOptions.data ? (
        <Fieldset legend="Hva skal ryddes?" hint="Bare koden endres – teksten, lenkene og innebygd innhold beholdes.">
          {cleanupOptions.data.options.map((o) => (
            <Checkbox
              key={o.id}
              label={o.label}
              checked={chosen.includes(o.id)}
              onChange={(e) => {
                setOptions(e.target.checked ? [...chosen, o.id] : chosen.filter((x) => x !== o.id));
              }}
            />
          ))}
        </Fieldset>
      ) : null}

      {previewMutation.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke lage forhåndsvisning">
          {(previewMutation.error as Error).message}
        </Alert>
      ) : null}
      {stageMutation.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke legge endringen i kø">
          {(stageMutation.error as Error).message}
        </Alert>
      ) : null}

      <div className="ek-cluster">
        <Button onClick={() => previewMutation.mutate({ key, params })} loading={previewMutation.isPending}>
          Forhåndsvis løsning
        </Button>
        <Button
          variant="primary"
          onClick={() => stageMutation.mutate()}
          loading={stageMutation.isPending}
          disabled={!preview}
          title={preview ? undefined : "Forhåndsvis løsningen først"}
        >
          Legg endring til kø
        </Button>
      </div>

      {preview ? (
        <div className="ek-stack">
          <div className="ek-cluster">
            <Badge tone={RISK[preview.risk]?.tone}>{RISK[preview.risk]?.label}</Badge>
            {preview.existing_change_id ? (
              <Badge tone="info">Slås sammen med en annen endring på samme side</Badge>
            ) : null}
          </div>
          <DiffView before={preview.before_display} after={preview.after_display} />
          <div className="ek-cluster" role="group" aria-label="Visning">
            {(["desktop", "tablet", "mobile"] as PreviewDevice[]).map((d) => (
              <Button key={d} size="sm" variant={device === d ? "primary" : "secondary"} aria-pressed={device === d}
                onClick={() => setDevice(d)}>
                {{ desktop: "PC", tablet: "Nettbrett", mobile: "Mobil" }[d]}
              </Button>
            ))}
          </div>
          <HtmlPreview html={preview.preview_html} title={`Forhåndsvisning av ${finding.object_title}`} device={device} />
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------------ structure suggestions */

interface StructureModules {
  modules: { id: string; name: string }[];
}

function StructureFixPanel({ finding, onStaged }: { finding: Finding; onStaged: () => void }) {
  const fix = finding.fix!;
  const params = (fix.params ?? {}) as Record<string, string>;
  const { courseId } = useCurrentCourse();
  const staged = useStagedToast();
  const [name, setName] = useState(params.name ?? "");
  const [moduleId, setModuleId] = useState(params.to_module ?? "");
  const [previewed, setPreviewed] = useState(false);
  const modules = useQuery({
    queryKey: ["structure", courseId],
    queryFn: () => api.get<StructureModules>(`/api/courses/${courseId}/structure`),
    enabled: fix.type === "move_item" && Boolean(courseId),
  });
  const stage = useMutation({
    mutationFn: () =>
      api.post(`/api/structure/findings/${finding.id}/stage`, fix.type === "rename_module" ? { name } : { module_id: moduleId }),
    onSuccess: () => {
      staged();
      onStaged();
    },
  });
  const moduleName = (id: string) => modules.data?.modules.find((m) => m.id === id)?.name ?? id;
  const evidence = finding.evidence as Record<string, unknown>;

  return (
    <div className="ek-stack">
      <h3>{fix.label}</h3>
      <p className="ek-small ek-muted">
        Forslaget er en anbefaling. Ingenting flyttes eller endres før du har godkjent det og gjennomført endringen fra
        endringskøen.
      </p>
      {fix.type === "rename_module" ? (
        <TextField label="Nytt navn på modulen" value={name} maxLength={255} onChange={(e) => {
          setName(e.target.value);
          setPreviewed(false);
        }} />
      ) : null}
      {fix.type === "move_item" ? (
        <SelectField
          label="Flytt til modul"
          value={moduleId}
          onChange={(e) => {
            setModuleId(e.target.value);
            setPreviewed(false);
          }}
          options={(modules.data?.modules ?? []).map((m) => ({ value: m.id, label: m.name }))}
        />
      ) : null}
      {previewed ? (
        <div className="ek-card ek-card--tone ek-card--compact" data-tone="info">
          <KeyValue
            items={
              fix.type === "rename_module"
                ? [["Nå", String(finding.object_title ?? "")], ["Etter endringen", name]]
                : [
                    ["Element", String(finding.object_title ?? "")],
                    ["Fra modul", String(evidence.current_module ?? moduleName(params.from_module))],
                    ["Til modul", moduleName(moduleId)],
                    ["Plassering", "Sist i modulen. Fullføringskrav på elementet beholdes."],
                  ]
            }
          />
        </div>
      ) : null}
      {stage.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke legge forslaget i kø">
          {(stage.error as Error).message}
        </Alert>
      ) : null}
      <div className="ek-cluster">
        <Button onClick={() => setPreviewed(true)}>Forhåndsvis</Button>
        <Button variant="primary" icon={<Check aria-hidden="true" />} onClick={() => stage.mutate()} loading={stage.isPending}
          disabled={!previewed || (fix.type === "rename_module" ? !name.trim() : !moduleId)}
          title={previewed ? undefined : "Forhåndsvis forslaget først"}>
          Godkjenn forslag
        </Button>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------- quiz suggestions */

interface QuizAnswer {
  text: string;
  correct: boolean;
}

function AnswerList({ answers, label }: { answers: QuizAnswer[]; label: string }) {
  return (
    <div className="ek-stack" data-gap="1">
      <span className="ek-strong ek-small">{label}</span>
      <ul className="ek-list-reset ek-stack" data-gap="1">
        {answers.map((a, i) => (
          <li key={i} className="ek-cluster" data-gap="2">
            {a.correct ? <Badge tone="success" icon={<Check aria-hidden="true" size={14} />}>Riktig</Badge> : <Badge>Feil</Badge>}
            <span className="ek-small">{a.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function QuizFixPanel({ finding, onStaged }: { finding: Finding; onStaged: () => void }) {
  const fix = finding.fix!;
  const params = (fix.params ?? {}) as { stem?: string; answers?: QuizAnswer[]; explanation?: string; changes_key?: boolean };
  const staged = useStagedToast();
  const [editing, setEditing] = useState(false);
  const [stem, setStem] = useState(params.stem ?? "");
  const [answers, setAnswers] = useState<QuizAnswer[]>(params.answers ?? []);
  const current = (finding.evidence.answers as QuizAnswer[] | undefined) ?? [];
  const stage = useMutation({
    mutationFn: (body: { stem?: string; answers?: QuizAnswer[] }) => api.post(`/api/quiz/findings/${finding.id}/stage`, body),
    onSuccess: () => {
      staged();
      onStaged();
    },
  });
  const valid = stem.trim() && answers.filter((a) => a.text.trim()).length >= 2 && answers.some((a) => a.correct);

  return (
    <div className="ek-stack">
      <div className="ek-cluster">
        <h3>Forslag til forbedret spørsmål</h3>
        <AiBadge />
      </div>
      {params.changes_key ? (
        <Alert tone="warning" title="Forslaget endrer fasiten">
          EmneKlar endrer aldri fasit automatisk. Kontroller kilden nøye. Endringen må bekreftes ekstra før den gjennomføres.
        </Alert>
      ) : null}
      {!editing ? (
        <>
          <p>
            <span className="ek-strong">Spørsmål: </span>
            {params.stem}
          </p>
          <div className="ek-grid" data-cols="2">
            <AnswerList answers={current} label="Nå" />
            <AnswerList answers={params.answers ?? []} label="Forslag" />
          </div>
          {params.explanation ? <p className="ek-small ek-muted">Begrunnelse: {params.explanation}</p> : null}
        </>
      ) : (
        <div className="ek-stack">
          <TextArea label="Spørsmålstekst" value={stem} onChange={(e) => setStem(e.target.value)} rows={3} maxLength={4000} />
          <Fieldset legend="Svaralternativer" hint="Merk av riktige svar. Minst to alternativer og minst ett riktig.">
            {answers.map((a, i) => (
              <div key={i} className="ek-cluster" data-align="end">
                <div className="ek-grow">
                  <TextField label={`Alternativ ${i + 1}`} value={a.text} maxLength={1000}
                    onChange={(e) => setAnswers(answers.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
                </div>
                <Checkbox label="Riktig" checked={a.correct}
                  onChange={(e) => setAnswers(answers.map((x, j) => (j === i ? { ...x, correct: e.target.checked } : x)))} />
                <IconButton label={`Fjern alternativ ${i + 1}`} onClick={() => setAnswers(answers.filter((_, j) => j !== i))}
                  disabled={answers.length <= 2}>
                  <Trash aria-hidden="true" size={16} />
                </IconButton>
              </div>
            ))}
            <div>
              <Button size="sm" icon={<Plus aria-hidden="true" />} onClick={() => setAnswers([...answers, { text: "", correct: false }])}
                disabled={answers.length >= 10}>
                Legg til alternativ
              </Button>
            </div>
          </Fieldset>
        </div>
      )}
      {stage.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke legge forslaget i kø">
          {(stage.error as Error).message}
        </Alert>
      ) : null}
      <div className="ek-cluster">
        {!editing ? (
          <>
            <Button variant="primary" icon={<Check aria-hidden="true" />} onClick={() => stage.mutate({})} loading={stage.isPending}>
              Godkjenn forslag
            </Button>
            <Button onClick={() => setEditing(true)}>Rediger</Button>
          </>
        ) : (
          <>
            <Button onClick={() => setEditing(false)}>Avbryt redigering</Button>
            <Button variant="primary" disabled={!valid} loading={stage.isPending}
              onClick={() => stage.mutate({ stem, answers: answers.filter((a) => a.text.trim()) })}>
              Legg redigert forslag i kø
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

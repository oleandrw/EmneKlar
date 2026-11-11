// Fixing a finding where it is shown. Every path ends in the change queue – nothing writes to Canvas directly.
//   HTML fixes (UU, innholdskvalitet): choose → automatic preview of exactly what changes → «Godkjenn» (approved in the
//   queue, next finding opens) – published with «Publiser til Canvas» from the queue.
//   Structure suggestions: «Forhåndsvis» → «Godkjenn forslag» (or «Avvis» = ignore)
//   Quiz suggestions: «Godkjenn forslag» / «Rediger» (or «Behold» = ignore)
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Plus, SkipForward, Trash } from "lucide-react";
import { useEffect, useState, type KeyboardEvent } from "react";

import { AiBadge } from "../../core/ai";
import { api } from "../../core/api/client";
import type { Finding } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { RISK } from "../../core/labels";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  DiffView,
  Disclosure,
  Fieldset,
  HtmlPreview,
  IconButton,
  KeyValue,
  RadioGroup,
  SelectField,
  type RadioOption,
  Spinner,
  TextArea,
  TextField,
  useToast,
  type PreviewDevice,
} from "../../design-system";
import { AiSuggestion } from "./AiSuggestion";
import { AltTextReview } from "./AltTextSuggestion";
import { VideoTitleSuggestion } from "./VideoTitleSuggestion";
import { findingAi, fixApprove, fixPreview, useFindingActions, type FixParams, type FixPreview, type FixScope, type LinkAction } from "./api";

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

export interface FixPanelProps {
  finding: Finding;
  /** After «Godkjenn»: the detail view moves on to the next finding (or closes). */
  onDone: () => void;
  /** «Hopp over»: go to the next finding without doing anything. */
  onSkip?: () => void;
  /** Ids of the next findings – their KI-forslag are prepared first. */
  upcoming?: number[];
  hasNext?: boolean;
}

export function FixPanel(props: FixPanelProps) {
  const { finding } = props;
  if (finding.domain === "structure") return <StructureFixPanel finding={finding} onStaged={props.onDone} />;
  if (finding.fix?.type === "quiz_question_update") return <QuizFixPanel finding={finding} onStaged={props.onDone} />;
  return <HtmlFixPanel {...props} />;
}

function useApprovedToast() {
  const toast = useToast();
  const actions = useFindingActions();
  return (extra?: string) => {
    actions.refresh();
    toast.show({
      tone: "success",
      title: "Godkjent – ligger i endringskøen",
      body: `${extra ? `${extra} ` : ""}Ingenting endres i Canvas før du velger «Publiser til Canvas» i endringskøen.`,
    });
  };
}

function useStagedToast() {
  const toast = useToast();
  const actions = useFindingActions();
  return () => {
    actions.refresh();
    toast.show({ tone: "success", title: "Lagt i endringskøen", body: "Godkjenn og publiser den fra endringskøen." });
  };
}

/** Debounced value – previews follow the teacher's typing without a request per keystroke. */
function useDebounced<T>(value: T, delay = 350): T {
  const [current, setCurrent] = useState(value);
  useEffect(() => {
    const handle = window.setTimeout(() => setCurrent(value), delay);
    return () => window.clearTimeout(handle);
  }, [value, delay]);
  return current;
}

/* ----------------------------------------------------------------------------- HTML fixes */

const AI_LABELS: Record<string, string> = {
  set_link_text: "Foreslå lenketekst med KI",
  table_caption: "Foreslå tabelltittel med KI",
  set_iframe_title: "Foreslå tittel med KI",
};

const TEXT_LABEL: Record<string, string> = {
  set_link_text: "Lenketekst",
  set_iframe_title: "Tittel på innebygd innhold",
  table_caption: "Tabelltittel",
};

function HtmlFixPanel({ finding, onDone, onSkip, upcoming = [], hasNext }: FixPanelProps) {
  const fix = finding.fix!;
  const approvedToast = useApprovedToast();
  const fixParams = (fix.params ?? {}) as Record<string, unknown>;
  const evidence = finding.evidence ?? {};
  const [text, setText] = useState<string>(String(fixParams.suggestion ?? ""));
  const [decorative, setDecorative] = useState(false);
  const [level, setLevel] = useState<string>(String(fixParams.level ?? 2));
  const [lang, setLang] = useState<string>(String(fixParams.lang ?? "en"));
  const [url, setUrl] = useState<string>(String(fixParams.suggestion ?? ""));
  // An empty link whose address cannot work is most likely a leftover: removing it is pre-selected (still a choice).
  const [linkAction, setLinkAction] = useState<LinkAction>(fixParams.default_action === "remove" ? "remove" : "replace");
  const emptyLink = Boolean(fixParams.empty);
  const [linkText, setLinkText] = useState<string>("");
  // The KI text put in the field (link text / text field). Cleared when the teacher empties the field.
  const [aiText, setAiText] = useState<string | null>(null);
  const [scope, setScope] = useState<FixScope>("this");
  const [options, setOptions] = useState<string[] | null>(null);
  const [device, setDevice] = useState<PreviewDevice>("desktop");

  const cleanupOptions = useQuery({
    queryKey: ["cleanup-options"],
    queryFn: () => api.get<{ options: { id: string; label: string }[] }>("/api/content-quality/cleanup-options"),
    enabled: fix.type === "cleanup",
    staleTime: Infinity,
  });
  const chosen = options ?? cleanupOptions.data?.options.map((o) => o.id) ?? [];
  const isLink = fix.type === "replace_link_href";
  const needsText = ["set_alt", "set_link_text", "set_iframe_title", "table_caption"].includes(fix.type);
  const needsLevel = ["change_heading_level", "convert_to_heading"].includes(fix.type);
  const params: FixParams = {
    text: needsText && !decorative ? text : undefined,
    decorative: fix.type === "set_alt" ? decorative : undefined,
    level: needsLevel ? Number(level) : undefined,
    lang: fix.type === "set_lang" ? lang : undefined,
    url: isLink && linkAction === "replace" ? url : undefined,
    link_action: isLink ? linkAction : undefined,
    link_text: isLink && linkAction === "replace" && linkText.trim() ? linkText : undefined,
    scope: isLink ? scope : undefined,
    options: fix.type === "cleanup" ? chosen : undefined,
  };
  const altSuggestion = finding.alt_suggestion?.suggestion;
  const usesAi = (aiText !== null && (isLink ? linkText.trim() : text.trim()) !== "")
    || (fix.type === "set_alt" && !decorative && Boolean(altSuggestion) && text.trim() === String(altSuggestion).trim());
  if (usesAi) params.ai_suggestion = true;
  const ready = !(needsText && !decorative && !text.trim()) && !(isLink && linkAction === "replace" && !url.trim())
    && !(isLink && emptyLink && linkAction === "replace" && !linkText.trim())
    && !(fix.type === "cleanup" && !cleanupOptions.data);
  const key = JSON.stringify(params);
  const debouncedKey = useDebounced(key);

  // The preview always belongs to exactly the current choices (the key travels with the request).
  const preview = useQuery({
    queryKey: ["fix-preview", finding.id, debouncedKey],
    queryFn: () => fixPreview(finding.id, JSON.parse(debouncedKey) as FixParams),
    enabled: ready,
    retry: false,
    staleTime: 60_000,
  });
  const current: FixPreview | undefined = debouncedKey === key ? preview.data : undefined;

  const approve = useMutation({
    mutationFn: () => fixApprove(finding.id, params),
    onSuccess: (result) => {
      const also = result.also_staged.length;
      approvedToast(also ? `Rettingen gjelder også ${also} annet innhold i emnet.` : undefined);
      onDone();
    },
  });
  const canApprove = ready && Boolean(current) && !preview.isFetching;
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && canApprove && !approve.isPending) {
      event.preventDefault();
      approve.mutate();
    }
  };

  const where = current?.where;
  return (
    <div className="ek-stack" data-gap="4" onKeyDown={onKeyDown}>
      <h3>{fix.label}</h3>

      {fix.type === "set_alt" ? (
        <AltTextReview finding={finding} upcoming={upcoming} text={text} setText={setText} decorative={decorative}
          setDecorative={setDecorative} />
      ) : null}

      {isLink ? (
        <LinkEditor finding={finding} action={linkAction} setAction={setLinkAction} url={url} setUrl={setUrl}
          linkText={linkText} setLinkText={(value) => {
            setLinkText(value);
            if (!value.trim()) setAiText(null);
          }} onAiText={setAiText} scope={scope} setScope={setScope} preview={current} />
      ) : null}

      {finding.href_problem && !isLink ? (
        <Alert tone="warning" title="Adressen er ugyldig">{finding.href_problem}</Alert>
      ) : null}

      {needsText && fix.type !== "set_alt" ? (
        <div className="ek-stack" data-gap="2">
          {fix.type === "set_link_text" ? (
            <p className="ek-small">
              <span className="ek-strong">Lenken går til: </span>
              <span className="ek-mono">{String(evidence.href ?? "–")}</span>
              {finding.location?.context ? <><br /><span className="ek-muted">Sammenheng: «{finding.location.context}»</span></> : null}
            </p>
          ) : null}
          <TextField label={TEXT_LABEL[fix.type] ?? "Tekst"} value={text} maxLength={200}
            onChange={(e) => {
              setText(e.target.value);
              if (!e.target.value.trim()) setAiText(null);
            }}
            hint={fix.type === "set_link_text" ? (fixParams.suggestion
              ? "Forslaget er laget ut fra lenkemålet. Rediger det så det sier hvor lenken går eller hva den gjør."
              : "Skriv en tekst som sier hvor lenken går eller hva den gjør.") : undefined} />
          {fix.type === "set_iframe_title" ? (
            <VideoTitleSuggestion finding={finding} text={text} setText={setText} initial={String(fixParams.suggestion ?? "")}
              onAiText={setAiText}
              fallback={<AiSuggestion label={AI_LABELS.set_iframe_title} findingId={finding.id} text={text} setText={setText}
                initial={String(fixParams.suggestion ?? "")} onSuggested={setAiText}
                prepare={() => findingAi.prepare(finding.id)} run={(confirmed, avoid) => findingAi.run(finding.id, confirmed, avoid)} />} />
          ) : AI_LABELS[fix.type] ? (
            <AiSuggestion label={AI_LABELS[fix.type]} findingId={finding.id} text={text} setText={setText}
              initial={String(fixParams.suggestion ?? "")} onSuggested={setAiText}
              prepare={() => findingAi.prepare(finding.id)} run={(confirmed, avoid) => findingAi.run(finding.id, confirmed, avoid)} />
          ) : null}
        </div>
      ) : null}
      {needsLevel ? (
        <div className="ek-stack" data-gap="2">
          {finding.location?.snippet ? <pre className="ek-code-block" aria-label="Elementet nå">{finding.location.snippet}</pre> : null}
          <SelectField label="Overskriftsnivå" value={level} onChange={(e) => setLevel(e.target.value)}
            hint={fixParams.level ? `Foreslått: nivå ${String(fixParams.level)} (siden har h1 som tittel).` : undefined}
            options={[2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `Overskrift ${n}` }))} />
        </div>
      ) : null}
      {fix.type === "set_lang" ? <SelectField label="Språk" value={lang} onChange={(e) => setLang(e.target.value)} options={LANGS} /> : null}
      {fix.type === "cleanup" && cleanupOptions.data ? (
        <Fieldset legend="Hva skal ryddes?" hint="Bare koden endres – teksten, lenkene og innebygd innhold beholdes.">
          {cleanupOptions.data.options.map((o) => (
            <Checkbox key={o.id} label={o.label} checked={chosen.includes(o.id)}
              onChange={(e) => setOptions(e.target.checked ? [...chosen, o.id] : chosen.filter((x) => x !== o.id))} />
          ))}
        </Fieldset>
      ) : null}

      {where && where.role !== "course" ? (
        <Alert tone={where.locked ? "warning" : "info"} title={where.role === "blueprint" ? "Blueprint-emne" : "Knyttet til Blueprint"}>
          {where.message}
        </Alert>
      ) : null}

      <section className="ek-stack" data-gap="2" aria-label="Slik blir det">
        <div className="ek-cluster" data-justify="between">
          <h4 className="ek-strong">Slik blir det</h4>
          {current ? (
            <span className="ek-cluster" data-gap="2">
              <Badge tone={RISK[current.risk]?.tone}>{RISK[current.risk]?.label}</Badge>
              {current.existing_change_id ? <Badge tone="info">Slås sammen med en annen retting på samme side</Badge> : null}
              {current.targeted ? <Badge tone="success">Bare dette elementet endres</Badge> : null}
            </span>
          ) : null}
        </div>
        {!ready ? (
          <p className="ek-small ek-muted">
            {isLink && emptyLink ? "Skriv lenketekst og adresse, eller velg å fjerne den tomme lenken."
              : isLink ? "Skriv den nye adressen, eller velg å fjerne lenken." : "Fyll inn feltet over, så vises endringen her."}
          </p>
        ) : preview.error && debouncedKey === key ? (
          <Alert tone="danger" role="alert" title="Kunne ikke lage forhåndsvisning">{(preview.error as Error).message}</Alert>
        ) : !current ? (
          <Spinner label="Lager forhåndsvisning …" />
        ) : current.targeted && current.changes.length ? (
          <ChangeSnippets changes={current.changes} />
        ) : (
          <DiffView before={current.before_display} after={current.after_display} />
        )}
        {current ? (
          <Disclosure summary="Hele siden før og etter">
            <div className="ek-stack">
              <DiffView before={current.before_display} after={current.after_display} />
              <div className="ek-cluster" role="group" aria-label="Visning">
                {(["desktop", "tablet", "mobile"] as PreviewDevice[]).map((d) => (
                  <Button key={d} size="sm" variant={device === d ? "primary" : "secondary"} aria-pressed={device === d}
                    onClick={() => setDevice(d)}>
                    {{ desktop: "PC", tablet: "Nettbrett", mobile: "Mobil" }[d]}
                  </Button>
                ))}
              </div>
              <HtmlPreview html={current.preview_html} title={`Forhåndsvisning av ${finding.object_title}`} device={device} />
            </div>
          </Disclosure>
        ) : null}
      </section>

      {approve.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke godkjenne">{(approve.error as Error).message}</Alert>
      ) : null}
      <div className="ek-review__actions">
        <Button variant="primary" icon={<Check aria-hidden="true" />} onClick={() => approve.mutate()} loading={approve.isPending}
          disabled={!canApprove} title={canApprove ? undefined : "Venter på forhåndsvisningen"}>
          {hasNext ? "Godkjenn og gå til neste" : "Godkjenn"}
        </Button>
        {onSkip && hasNext ? (
          <Button icon={<SkipForward aria-hidden="true" />} onClick={onSkip}>Hopp over</Button>
        ) : null}
        <span className="ek-xs ek-muted ek-review__hint">Ctrl + Enter godkjenner · Alt + N neste · Alt + P forrige</span>
      </div>
    </div>
  );
}

function ChangeSnippets({ changes }: { changes: { before: string; after: string }[] }) {
  const shown = changes.slice(0, 5);
  return (
    <div className="ek-stack" data-gap="2">
      {shown.map((c, i) => (
        <div key={i} className="ek-change-snippet">
          <div>
            <span className="ek-change-snippet__label">Nå</span>
            <pre>{c.before || "–"}</pre>
          </div>
          <div>
            <span className="ek-change-snippet__label">Etter rettingen</span>
            <pre>{c.after || "(fjernet)"}</pre>
          </div>
        </div>
      ))}
      {changes.length > shown.length ? <p className="ek-xs ek-muted">… og {changes.length - shown.length} til på samme side.</p> : null}
    </div>
  );
}

/** Dead or problematic links: replace the address (and text), remove the link but keep the text, or remove it all –
 * for this occurrence, every occurrence on the page, or every place in the course. Always the teacher's choice. */
function LinkEditor({ finding, action, setAction, url, setUrl, linkText, setLinkText, onAiText, scope, setScope, preview }: {
  finding: Finding;
  onAiText: (text: string) => void;
  action: LinkAction;
  setAction: (value: LinkAction) => void;
  url: string;
  setUrl: (value: string) => void;
  linkText: string;
  setLinkText: (value: string) => void;
  scope: FixScope;
  setScope: (value: FixScope) => void;
  preview: FixPreview | undefined;
}) {
  const evidence = finding.evidence ?? {};
  const fixParams = (finding.fix?.params ?? {}) as Record<string, unknown>;
  const href = String(evidence.href ?? "");
  const currentText = String(evidence.link_text ?? fixParams.text ?? "");
  const occurrences = preview?.occurrences ?? Number(evidence.occurrences ?? 1);
  const related = preview?.related ?? [];
  const suggestion = fixParams.suggestion;
  const empty = Boolean(fixParams.empty);
  const actions: RadioOption<LinkAction>[] = empty ? [
    {
      value: "remove", label: "Fjern den tomme lenken",
      hint: "Lenken har ingen tekst og er usynlig på siden – bare skjermlesere finner den. Ingenting av det som vises, forsvinner.",
    },
    { value: "replace", label: "Gi lenken tekst og riktig adresse", hint: "Lenken blir synlig og klikkbar med teksten du skriver." },
  ] : [
    { value: "replace", label: "Erstatt adressen", hint: "Lenken beholdes med ny adresse (og eventuelt ny tekst)." },
    { value: "unlink", label: "Fjern lenken, behold teksten", hint: currentText ? `«${currentText}» blir vanlig tekst.` : "Teksten blir stående som vanlig tekst." },
    { value: "remove", label: "Fjern hele lenken", hint: "Både lenken og lenketeksten fjernes. Teksten rundt beholdes." },
  ];
  return (
    <div className="ek-stack" data-gap="3">
      <KeyValue items={[
        ["Lenken nå", <span key="h" className="ek-mono">{href || "–"}</span>],
        ["Lenketekst", currentText ? `«${currentText}»` : "ingen tekst"],
        ...(evidence.http_status ? [["Svar fra nettstedet", `HTTP ${String(evidence.http_status)}`] as [string, string]] : []),
        ...(finding.location?.context ? [["Teksten rundt", `«${finding.location.context}»`] as [string, string]] : []),
      ]} />
      {finding.href_problem ? (
        <Alert tone="warning" title="Adressen er ugyldig">
          {finding.href_problem}
          {empty ? " Lenken kan derfor ikke ha virket, og å fjerne den er sannsynligvis riktig." : ""}
        </Alert>
      ) : null}
      <RadioGroup<LinkAction>
        legend="Hva vil du gjøre?"
        name={`link-action-${finding.id}`}
        value={action}
        onChange={setAction}
        options={actions}
      />
      {action === "replace" ? (
        <div className="ek-grid" data-cols="2">
          <TextField label={empty ? "Adresse" : "Ny adresse"} type="url" value={url} placeholder="https://"
            onChange={(e) => setUrl(e.target.value)}
            hint={suggestion && !empty ? "Forslaget er adressen lenken nå sender videre til. Kontroller at den er riktig." :
              empty && suggestion ? "Adressen lenken har i dag. Endre den om den er feil." : "Lim inn adressen lenken skal gå til."} />
          <TextField label={empty ? "Lenketekst" : "Ny lenketekst"} optional={!empty} value={linkText} maxLength={200}
            onChange={(e) => setLinkText(e.target.value)}
            hint={empty ? "Teksten som vises på siden. Skriv hva lenken går til, for eksempel «Pensumliste (PDF)»." :
              "La stå tom for å beholde teksten."} />
        </div>
      ) : null}
      {action === "replace" && empty ? (
        <AiSuggestion label="Foreslå lenketekst med KI" findingId={finding.id} text={linkText} setText={setLinkText} initial=""
          onSuggested={onAiText}
          prepare={() => findingAi.prepare(finding.id, url.trim() || undefined)}
          run={(confirmed, avoid) => findingAi.run(finding.id, confirmed, avoid, url.trim() || undefined)} />
      ) : null}
      <RadioGroup<FixScope>
        legend="Gjelder"
        name={`link-scope-${finding.id}`}
        value={scope}
        onChange={setScope}
        options={[
          { value: "this", label: "Bare denne forekomsten" },
          { value: "page", label: `Alle forekomster i «${finding.object_title}» (${occurrences})`, disabled: occurrences < 2 },
          {
            value: "course",
            label: `Alle steder i emnet (${occurrences} her + ${related.length} ${related.length === 1 ? "annet innhold" : "andre innhold"})`,
            disabled: related.length === 0,
            hint: related.length ? related.slice(0, 4).map((r) => r.object_title).join(", ") + (related.length > 4 ? " …" : "") : undefined,
          },
        ]}
      />
      <p className="ek-xs ek-muted">EmneKlar sletter aldri lenker automatisk – det skjer bare når du velger det her.</p>
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
        Forslaget er en anbefaling. Ingenting flyttes eller endres før du har godkjent det og publisert endringen fra
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
          EmneKlar endrer aldri fasit automatisk. Kontroller kilden nøye. Endringen må bekreftes ekstra før den publiseres.
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

// «Standardiser videoavspillere» (Innholdskvalitet → Media): YouTube embeds in one responsive, accessible standard.
//   Finn videoer (job) → oversikt → detalj: Forhåndsvis → Godkjenn → endringskøen. Masse-standardisering likeså.
// Nothing is written to Canvas from here: every approval is staged in the global change queue.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Eye, ListPlus, Maximize, Pencil, Search, Sparkles, TriangleAlert, Type, Wrench } from "lucide-react";
import { useMemo, useState } from "react";

import { AiBadge, AiConsent, AiNotConfigured, useAiConfigured, type AiPlan } from "../../core/ai";
import { ApiError, api } from "../../core/api/client";
import type { Job } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime } from "../../core/format";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  DataTable,
  Dialog,
  DiffView,
  EmptyState,
  ExternalLink,
  Fieldset,
  FilterChips,
  HtmlPreview,
  KeyFigure,
  KeyFigureList,
  KeyValue,
  RadioGroup,
  Spinner,
  TextField,
  useToast,
  type Column,
  type PreviewDevice,
  type Tone,
} from "../../design-system";
import { JobRunner } from "../analysis/JobRunner";
import type { JobWording } from "../analysis/ProgressPanel";

type TitleSource = "existing" | "youtube_metadata" | "page_context" | "ai_suggestion" | "manual";
type VideoStatus = "no_change" | "safe" | "needs_title" | "manual";
type ObjectType = "page" | "assignment" | "discussion" | "quiz" | "syllabus";

interface VideoOptions {
  max_width: number | null;
  keep_ratio: boolean;
  responsive: boolean;
  center: boolean;
  lazy: boolean;
  fix_title: boolean;
}

interface TitleProposal {
  title: string | null;
  source: TitleSource | null;
  source_label: string | null;
  needs_review: boolean;
}

export interface VideoItem {
  key: string;
  object_type: ObjectType;
  object_id: string;
  object_title: string;
  location: string;
  modules: string[];
  html_url: string | null;
  queued: boolean;
  video_id: string;
  occurrence: number;
  supported: boolean;
  src: string;
  youtube_title: string | null;
  metadata_status: string | null;
  metadata_message: string | null;
  current: { title: string; size: string | null; layout: string };
  issues: { code: string; label: string }[];
  autoplay: boolean;
  proposed: { title: TitleProposal; layout: string; changes_markup: boolean };
  status: VideoStatus;
  status_label: string;
  manual_reason: string | null;
  context: { page_title: string; heading: string };
}

interface Summary {
  videos: number;
  unique_videos: number;
  standard: number;
  safe: number;
  needs_title: number;
  manual: number;
  fixed_size: number;
  missing_title: number;
  old_embed: number;
  autoplay: number;
}

interface ScanResult {
  snapshot_at: string;
  items: VideoItem[];
  summary: Summary;
  errors: { object_title: string; location: string; message: string }[];
  options: VideoOptions;
  scope: "course" | "modules";
  module_ids: string[];
}

interface LatestScan {
  job_id: string | null;
  finished_at: string | null;
  result: ScanResult | null;
}

interface VideoPreview {
  existing_change_id: number | null;
  no_change: boolean;
  title: string | null;
  title_source: TitleSource | null;
  title_source_label: string | null;
  layout: string;
  manual_reason: string | null;
  autoplay: boolean;
  before_display: string;
  after_display: string;
  before_preview: string;
  after_preview: string;
}

interface AiTitle {
  title: string;
  source_label: string;
  label: string;
  provider: string;
  model: string;
}

interface ContentIndex {
  modules: { id: string; name: string; items_count: number }[];
}

const STATUS_TONE: Record<VideoStatus, Tone> = {
  no_change: "success",
  safe: "info",
  needs_title: "warning",
  manual: "danger",
};

const SOURCE_TONE: Record<TitleSource, Tone> = {
  existing: "success",
  youtube_metadata: "info",
  page_context: "warning",
  ai_suggestion: "violet",
  manual: "neutral",
};

const SOURCE_LABEL: Record<TitleSource, string> = {
  existing: "Eksisterende title",
  youtube_metadata: "YouTube-metadata",
  page_context: "Canvas-kontekst",
  ai_suggestion: "KI-forslag",
  manual: "Skrevet inn manuelt",
};

const SCAN_WORDING: JobWording = {
  noun: "skanningen",
  current: "Nå hentes",
  findingsTitle: "Videoer",
  findingsEmpty: "Oversikten vises når skanningen er ferdig.",
  cancelNote: "Skanningen stoppes. Ingenting er endret i Canvas.",
};

type WidthChoice = "960" | "800" | "full" | "custom";

interface FormState {
  scope: "course" | "modules";
  moduleIds: string[];
  width: WidthChoice;
  customWidth: string;
  ratio: "16:9" | "keep";
  responsive: boolean;
  center: boolean;
  lazy: boolean;
  fixTitle: boolean;
}

const DEFAULT_FORM: FormState = {
  scope: "course",
  moduleIds: [],
  width: "960",
  customWidth: "720",
  ratio: "16:9",
  responsive: true,
  center: true,
  lazy: true,
  fixTitle: true,
};

function customWidthError(form: FormState): string | null {
  if (form.width !== "custom") return null;
  const value = Number(form.customWidth);
  return Number.isInteger(value) && value >= 320 && value <= 1920 ? null : "Skriv en bredde mellom 320 og 1920 piksler.";
}

function toOptions(form: FormState): VideoOptions {
  const max_width = form.width === "full" ? null : form.width === "custom" ? Number(form.customWidth) : Number(form.width);
  return {
    max_width,
    keep_ratio: form.ratio === "keep",
    responsive: form.responsive,
    center: form.center,
    lazy: form.lazy,
    fix_title: form.fixTitle,
  };
}

function sameOptions(a: VideoOptions, b: VideoOptions): boolean {
  return (Object.keys(a) as (keyof VideoOptions)[]).every((k) => a[k] === b[k]);
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function SourceBadge({ source }: { source: TitleSource | null }) {
  if (!source) return <Badge tone="neutral">Kilde: ingen – må skrives inn</Badge>;
  return <Badge tone={SOURCE_TONE[source]}>Kilde: {SOURCE_LABEL[source]}</Badge>;
}

function itemRef(item: VideoItem) {
  return {
    object_type: item.object_type,
    object_id: item.object_id,
    object_title: item.object_title,
    video_id: item.video_id,
    occurrence: item.occurrence,
  };
}

function useStagedToast() {
  const toast = useToast();
  const client = useQueryClient();
  return (title: string, body?: string) => {
    void client.invalidateQueries({ queryKey: ["changes"] });
    toast.show({
      tone: "success",
      title,
      body: [
        body,
        "Godkjenn og publiser endringene fra endringskøen.",
      ]
        .filter(Boolean)
        .join(" "),
    });
  };
}

/* ------------------------------------------------------------------------------- main panel */

export function VideoStandardiser() {
  const { courseId } = useCurrentCourse();
  const client = useQueryClient();
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobEnded, setJobEnded] = useState(false);

  const latest = useQuery({
    queryKey: ["video-scan", courseId],
    queryFn: () => api.get<LatestScan>(`/api/courses/${courseId}/videos/latest`),
    enabled: Boolean(courseId),
  });
  const index = useQuery({
    queryKey: ["content-index", courseId],
    queryFn: () => api.get<ContentIndex>(`/api/courses/${courseId}/content-index`),
    enabled: Boolean(courseId) && form.scope === "modules",
  });
  const start = useMutation({
    mutationFn: () =>
      api.post<Job>(`/api/courses/${courseId}/videos/scan`, {
        module_ids: form.scope === "modules" ? form.moduleIds : [],
        options: toOptions(form),
      }),
    onSuccess: (job) => {
      setJobEnded(false);
      setJobId(job.id);
    },
    onError: (error) => {
      // A scan that is already running for this course: follow it instead of starting another.
      const running = error instanceof ApiError && error.code === "job_already_running" ? error.extra?.job_id : null;
      if (typeof running === "string") {
        setJobEnded(false);
        setJobId(running);
      }
    },
  });

  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;

  const update = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }));
  const widthError = customWidthError(form);
  const running = jobId !== null && !jobEnded;
  const startError = start.error instanceof ApiError && start.error.code !== "job_already_running" ? start.error : null;
  const result = latest.data?.result ?? null;

  return (
    <div className="ek-stack" data-gap="6">
      <Card
        title="Standardiser videoavspillere"
        description="Finner YouTube-videoer i emnet og foreslår én responsiv standard med beskrivende title. Godkjente endringer legges i endringskøen – ingenting endres i Canvas før du gjennomfører køen."
      >
        <div className="ek-stack" data-gap="6">
          <RadioGroup
            legend="Omfang"
            name="video-scope"
            value={form.scope}
            onChange={(scope) => update({ scope })}
            options={[
              { value: "course", label: "Hele emnet" },
              { value: "modules", label: "Valgte moduler" },
            ]}
          />
          {form.scope === "modules" ? (
            index.isPending ? (
              <Spinner label="Henter moduler …" />
            ) : index.error ? (
              <Alert tone="danger" role="alert" title="Kunne ikke hente modulene">
                {(index.error as Error).message}
              </Alert>
            ) : (
              <Fieldset legend="Moduler" hint={`${form.moduleIds.length} valgt`}>
                {(index.data?.modules ?? []).map((m) => (
                  <Checkbox
                    key={m.id}
                    label={`${m.name} (${m.items_count} elementer)`}
                    checked={form.moduleIds.includes(m.id)}
                    onChange={(e) =>
                      update({
                        moduleIds: e.target.checked ? [...form.moduleIds, m.id] : form.moduleIds.filter((x) => x !== m.id),
                      })
                    }
                  />
                ))}
              </Fieldset>
            )
          ) : null}
          <div className="ek-grid" data-cols="2">
            <div className="ek-stack" data-gap="2">
              <RadioGroup
                legend="Standard videobredde"
                name="video-width"
                value={form.width}
                onChange={(width) => update({ width })}
                options={[
                  { value: "960", label: "Maks 960 px" },
                  { value: "800", label: "Maks 800 px" },
                  { value: "full", label: "Full tilgjengelig bredde" },
                  { value: "custom", label: "Egendefinert" },
                ]}
              />
              {form.width === "custom" ? (
                <TextField
                  label="Maks bredde i piksler"
                  type="number"
                  inputMode="numeric"
                  min={320}
                  max={1920}
                  value={form.customWidth}
                  error={widthError ?? undefined}
                  onChange={(e) => update({ customWidth: e.target.value })}
                />
              ) : null}
            </div>
            <RadioGroup
              legend="Format"
              name="video-ratio"
              value={form.ratio}
              onChange={(ratio) => update({ ratio })}
              options={[
                { value: "16:9", label: "16:9" },
                {
                  value: "keep",
                  label: "Behold eksisterende format",
                  hint: "Bruker forholdet mellom bredde og høyde i dagens kode. Uten mål brukes 16:9.",
                },
              ]}
            />
          </div>
          <Fieldset legend="Valg">
            <Checkbox
              label="Responsiv visning"
              hint="Videoen fyller tilgjengelig bredde og krymper på nettbrett og mobil."
              checked={form.responsive}
              onChange={(e) => update({ responsive: e.target.checked })}
            />
            <Checkbox label="Sentrer videoer" checked={form.center} onChange={(e) => update({ center: e.target.checked })} />
            <Checkbox
              label="Lazy loading når Canvas støtter det"
              hint="Videoen lastes først når den nærmer seg skjermen. Canvas beholder loading-attributtet."
              checked={form.lazy}
              onChange={(e) => update({ lazy: e.target.checked })}
            />
            <Checkbox
              label="Kontroller beskrivende iframe-title"
              checked={form.fixTitle}
              onChange={(e) => update({ fixTitle: e.target.checked })}
            />
          </Fieldset>
          <div className="ek-cluster">
            <Button
              variant="primary"
              icon={<Search aria-hidden="true" />}
              onClick={() => start.mutate()}
              loading={start.isPending}
              disabled={running || Boolean(widthError) || (form.scope === "modules" && form.moduleIds.length === 0)}
            >
              {result ? "Skann videoene på nytt" : "Finn videoer"}
            </Button>
          </div>
          {startError ? (
            <Alert
              tone="danger"
              role="alert"
              title="Kunne ikke starte skanningen"
            >
              {startError.message}
              {startError.code === "snapshot_missing" ? " Start med «Analyser innholdskvalitet» øverst til høyre." : null}
            </Alert>
          ) : null}
          {jobId ? (
            <JobRunner
              jobId={jobId}
              wording={SCAN_WORDING}
              onDone={(job) => {
                void client.invalidateQueries({ queryKey: ["video-scan", courseId] });
                // A failed or cancelled scan keeps its panel so the reason stays visible.
                if (job.status === "completed") setJobId(null);
                else setJobEnded(true);
              }}
            />
          ) : null}
        </div>
      </Card>

      {latest.isPending ? (
        <Spinner label="Henter siste skanning …" />
      ) : latest.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke hente siste skanning">
          {(latest.error as Error).message}
        </Alert>
      ) : result ? (
        <ScanResults
          key={latest.data.job_id ?? "none"}
          result={result}
          finishedAt={latest.data.finished_at}
          formOptions={toOptions(form)}
        />
      ) : !running ? (
        <EmptyState title="Ingen skanning ennå" headingLevel={3}>
          Trykk «Finn videoer». EmneKlar leser bare fra Canvas og YouTube – ingenting endres før du godkjenner.
        </EmptyState>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------------------------- results */

type Filter = "todo" | "all" | VideoStatus | "ignored";

function ScanResults({ result, finishedAt, formOptions }: { result: ScanResult; finishedAt: string | null; formOptions: VideoOptions }) {
  const [ignored, setIgnored] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>("todo");
  const [open, setOpen] = useState<VideoItem | null>(null);
  const { summary, items } = result;
  const options = result.options;

  const visible = useMemo(
    () =>
      items.filter((item) => {
        const isIgnored = ignored.includes(item.key);
        if (filter === "ignored") return isIgnored;
        if (isIgnored) return false;
        if (filter === "all") return true;
        if (filter === "todo") return item.status !== "no_change";
        return item.status === filter;
      }),
    [items, ignored, filter],
  );
  const statusCount = (status: VideoStatus) => items.filter((i) => i.status === status && !ignored.includes(i.key)).length;

  const columns: Column<VideoItem>[] = [
    {
      key: "page",
      header: "Side",
      rowHeader: true,
      cell: (item) => (
        <span className="ek-stack" data-gap="1">
          <span>{item.location}</span>
          {item.queued ? <Badge tone="info">Har endring i køen</Badge> : null}
        </span>
      ),
    },
    {
      key: "video",
      header: "Video",
      cell: (item) => (
        <span className="ek-stack" data-gap="1">
          <span className="ek-small">{item.video_id ? `YouTube-ID: ${item.video_id}` : "Ukjent video-ID"}</span>
          {item.youtube_title ? <span className="ek-xs ek-muted">{item.youtube_title}</span> : null}
          {item.autoplay ? <Badge tone="warning">Starter automatisk</Badge> : null}
        </span>
      ),
    },
    {
      key: "current",
      header: "Nåværende",
      cell: (item) => (
        <span className="ek-stack" data-gap="1">
          <span className="ek-small">
            {item.current.layout}
            {item.current.size ? ` (${item.current.size})` : ""}
          </span>
          <span className="ek-xs ek-muted">{item.current.title ? `title: «${item.current.title}»` : "Mangler title"}</span>
        </span>
      ),
    },
    {
      key: "proposed",
      header: "Foreslått title",
      cell: (item) =>
        item.supported ? (
          <span className="ek-stack" data-gap="1">
            <span className="ek-small">{item.proposed.title.title ? `«${item.proposed.title.title}»` : "–"}</span>
            <SourceBadge source={item.proposed.title.source} />
          </span>
        ) : (
          "–"
        ),
    },
    {
      key: "status",
      header: "Status",
      cell: (item) => (
        <span className="ek-stack" data-gap="1">
          <Badge tone={STATUS_TONE[item.status]}>{item.status_label}</Badge>
          {item.issues.length ? <span className="ek-xs ek-muted">{item.issues.map((i) => i.label).join(", ")}</span> : null}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="ek-visually-hidden">Handlinger</span>,
      cell: (item) => (
        <Button size="sm" onClick={() => setOpen(item)}>
          Vis detaljer<span className="ek-visually-hidden">: {item.location}, video {item.video_id || "uten ID"}</span>
        </Button>
      ),
    },
  ];

  return (
    <div className="ek-stack" data-gap="6">
      <Card
        title={`${count(summary.videos, "YouTube-video", "YouTube-videoer")} funnet`}
        description={[
          finishedAt ? `Skannet ${formatDateTime(finishedAt)}` : null,
          result.scope === "modules" ? "valgte moduler" : "hele emnet",
          summary.unique_videos !== summary.videos ? `${summary.unique_videos} ulike videoer (noen er brukt flere steder)` : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      >
        <KeyFigureList label="Videooversikt">
          <KeyFigure icon={<CircleCheck />} tone="success" value={summary.standard} label="følger EmneKlar-standard" />
          <KeyFigure icon={<Maximize />} tone="warning" value={summary.fixed_size} label="har fast størrelse" />
          <KeyFigure icon={<Type />} tone="warning" value={summary.missing_title} label="mangler beskrivende videotittel" />
          <KeyFigure icon={<Wrench />} tone="info" value={summary.old_embed} label="bruker avvikende eller gammel embed-kode" />
          <KeyFigure icon={<TriangleAlert />} tone="danger" value={summary.manual} label="krever manuell kontroll" />
        </KeyFigureList>
        <p className="ek-xs ek-muted ek-mt-2">
          En video kan ha flere problemer og telles da under hvert av dem, men bare én gang i totalen.
        </p>
      </Card>

      {!sameOptions(options, formOptions) ? (
        <Alert tone="info" title="Valgene er endret siden skanningen">
          Oversikten, forhåndsvisningen og masse-standardiseringen bruker valgene fra skanningen. Skann på nytt for å bruke
          de nye valgene.
        </Alert>
      ) : null}
      {summary.autoplay ? (
        <Alert tone="warning" title={`${summary.autoplay} ${summary.autoplay === 1 ? "video starter" : "videoer starter"} automatisk`}>
          Automatisk avspilling kan forstyrre, særlig for skjermleserbrukere. EmneKlar endrer ikke dette – vurder å fjerne
          «autoplay=1» fra videoadressen i Canvas.
        </Alert>
      ) : null}
      {result.errors.length ? (
        <Alert tone="warning" title="Noen sider kunne ikke hentes fra Canvas">
          <ul>
            {result.errors.map((e) => (
              <li key={e.location}>
                {e.location}: {e.message}
              </li>
            ))}
          </ul>
        </Alert>
      ) : null}

      <BulkCard result={result} ignored={ignored} />

      <section className="ek-stack" data-gap="4" aria-labelledby="video-liste">
        <h2 id="video-liste">Videoer</h2>
        <p className="ek-small ek-muted">
          Videoene finnes ut fra siste analyse ({formatDateTime(result.snapshot_at)}), og sidene hentes på nytt fra Canvas ved
          hver skanning. En beskrivende title gjør videoen lettere å forstå for skjermleserbrukere, men betyr ikke at selve
          videoen er universelt utformet – teksting, transkripsjon og synstolking vurderes separat.
        </p>
        <FilterChips
          label="Vis"
          showLabel
          value={filter}
          onChange={setFilter}
          options={[
            { value: "todo", label: "Bør endres", count: items.filter((i) => i.status !== "no_change" && !ignored.includes(i.key)).length },
            { value: "all", label: "Alle", count: items.length - ignored.length },
            { value: "safe", label: "Kan standardiseres trygt", count: statusCount("safe") },
            { value: "needs_title", label: "Trenger godkjenning av title", count: statusCount("needs_title") },
            { value: "manual", label: "Krever manuell kontroll", count: statusCount("manual") },
            { value: "no_change", label: "Ingen endring nødvendig", count: statusCount("no_change") },
            ...(ignored.length ? [{ value: "ignored" as const, label: "Ignorert", count: ignored.length }] : []),
          ]}
        />
        <DataTable
          caption={`Videoer (${visible.length})`}
          columns={columns}
          rows={visible}
          rowKey={(item) => item.key}
          empty={filter === "todo" ? "Alle videoene følger standarden." : "Ingen videoer med dette valget."}
        />
      </section>

      <Dialog
        open={open !== null}
        onClose={() => setOpen(null)}
        title="Video"
        description={open?.location}
        size="xl"
      >
        {open ? (
          <VideoDetail
            key={open.key}
            item={open}
            options={options}
            ignored={ignored.includes(open.key)}
            onIgnore={(value) => {
              setIgnored((current) => (value ? [...current, open.key] : current.filter((k) => k !== open.key)));
              setOpen(null);
            }}
            onStaged={() => setOpen(null)}
          />
        ) : null}
      </Dialog>
    </div>
  );
}

/* ------------------------------------------------------------------------------------- bulk */

function BulkCard({ result, ignored }: { result: ScanResult; ignored: string[] }) {
  const { courseId } = useCurrentCourse();
  const ui = useUi();
  const toast = useToast();
  const staged = useStagedToast();
  const [confirm, setConfirm] = useState(false);
  const [choices, setChoices] = useState({
    standardise_size: true,
    center: true,
    add_title_from_metadata: true,
    replace_generic_title: true,
    overwrite_existing_title: false,
  });
  const { summary } = result;
  const eligible = result.items.filter(
    (i) => i.supported && (i.status === "safe" || i.status === "needs_title") && !ignored.includes(i.key),
  );
  const pages = new Set(eligible.map((i) => `${i.object_type}:${i.object_id}`)).size;
  const needsTitle = eligible.filter((i) => i.status === "needs_title").length;
  const bulk = useMutation({
    mutationFn: () =>
      api.post<{ changes: number; videos: number; titles: number; unchanged: number; skipped: { object_title: string; reason: string }[] }>(
        `/api/courses/${courseId}/videos/stage-bulk`,
        { items: eligible.map(itemRef), options: result.options, ...choices },
      ),
    onSuccess: (data) => {
      setConfirm(false);
      const skipped = data.skipped.length ? ` ${data.skipped.length} hoppet over: ${data.skipped.map((s) => s.reason).join(" ")}` : "";
      if (data.changes === 0) {
        toast.show({
          tone: "info",
          title: "Ingen nye endringer",
          body: `Videoene følger allerede standarden, eller endringen ligger allerede i endringskøen.${skipped}`,
        });
        return;
      }
      staged(
        `${count(data.changes, "endring", "endringer")} lagt i endringskøen`,
        `${count(data.videos, "video", "videoer")} på ${count(data.changes, "side", "sider")}, ${data.titles} med ny title fra YouTube-metadata.${skipped}`,
      );
      ui.openChanges();
    },
  });
  const set = (key: keyof typeof choices) => (e: { target: { checked: boolean } }) =>
    setChoices((current) => ({ ...current, [key]: e.target.checked }));

  return (
    <Card
      title="Standardiser alle kompatible videoer"
      description="Legger én endring per side i endringskøen. Ingenting endres i Canvas før du gjennomfører køen."
    >
      <div className="ek-stack" data-gap="4">
        <ul className="ek-small">
          <li>{count(summary.videos, "video", "videoer")} analysert</li>
          <li>{summary.standard} trenger ingen endring</li>
          <li>{summary.safe} kan standardiseres trygt</li>
          <li>{summary.needs_title} trenger godkjenning av title</li>
          <li>{summary.manual} krever manuell kontroll</li>
        </ul>
        <Fieldset legend="Hva skal gjøres?">
          <Checkbox label="Standardiser responsiv størrelse" checked={choices.standardise_size} onChange={set("standardise_size")} />
          <Checkbox label="Sentrer video" checked={choices.center} onChange={set("center")} />
          <Checkbox
            label="Legg til beskrivende title når god metadata finnes"
            checked={choices.add_title_from_metadata}
            onChange={set("add_title_from_metadata")}
          />
          <Checkbox label="Erstatt manglende eller generiske titler" checked={choices.replace_generic_title} onChange={set("replace_generic_title")} />
          <Checkbox
            label="Erstatt også gode eksisterende titler"
            hint="Når dette er av, beholdes titler som allerede beskriver videoen godt."
            checked={choices.overwrite_existing_title}
            onChange={set("overwrite_existing_title")}
          />
        </Fieldset>
        <p className="ek-small ek-muted">
          Nye titler hentes bare fra YouTube-metadata. Titler fra Canvas-kontekst eller KI må godkjennes én og én i
          detaljvisningen. Videoer som krever manuell kontroll eller er ignorert, tas ikke med.
        </p>
        <div className="ek-cluster">
          <Button
            variant="primary"
            icon={<ListPlus aria-hidden="true" />}
            onClick={() => setConfirm(true)}
            disabled={eligible.length === 0}
          >
            Standardiser alle kompatible videoer
          </Button>
          {eligible.length === 0 ? <span className="ek-small ek-muted">Ingen videoer trenger endring.</span> : null}
        </div>
        {bulk.error ? (
          <Alert tone="danger" role="alert" title="Kunne ikke legge endringene i kø">
            {(bulk.error as Error).message}
          </Alert>
        ) : null}
      </div>
      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => bulk.mutate()}
        loading={bulk.isPending}
        title="Legge videoene i endringskøen?"
        confirmLabel="Legg i endringskøen"
      >
        <p>
          {eligible.length} {eligible.length === 1 ? "video" : "videoer"} på {pages} {pages === 1 ? "side" : "sider"} blir
          vurdert. Hver side får én endring i køen, og bare koden for selve videoene endres.
        </p>
        {needsTitle ? (
          <p>
            {needsTitle} av dem mangler en sikker title. Den endres ikke her – godkjenn title for dem i detaljvisningen.
          </p>
        ) : null}
        <p>Ingenting sendes til Canvas før du gjennomfører endringskøen.</p>
      </ConfirmDialog>
    </Card>
  );
}

/* ----------------------------------------------------------------------------------- detail */

function initialTitle(item: VideoItem): { title: string; source: TitleSource | null } {
  const proposed = item.proposed.title;
  return proposed.title ? { title: proposed.title, source: proposed.source } : { title: "", source: null };
}

function VideoDetail({
  item,
  options,
  ignored,
  onIgnore,
  onStaged,
}: {
  item: VideoItem;
  options: VideoOptions;
  ignored: boolean;
  onIgnore: (ignore: boolean) => void;
  onStaged: () => void;
}) {
  const { courseId } = useCurrentCourse();
  const staged = useStagedToast();
  const aiConfigured = useAiConfigured();
  const start = initialTitle(item);
  const [title, setTitle] = useState(start.title);
  const [source, setSource] = useState<TitleSource | null>(start.source);
  const [editing, setEditing] = useState(false);
  const [device, setDevice] = useState<PreviewDevice>("desktop");
  const [plan, setPlan] = useState<AiPlan | null>(null);
  const [aiTitle, setAiTitle] = useState<AiTitle | null>(null);
  const [previewed, setPreviewed] = useState<{ key: string; data: VideoPreview } | null>(null);

  const chosen = title.trim();
  const body = {
    ...itemRef(item),
    options,
    title: chosen || null,
    title_source: chosen ? (source ?? "manual") : null,
  };
  // The preview belongs to exactly these choices; any change (title, KI-forslag …) requires a new one.
  const key = JSON.stringify(body);
  const preview = previewed?.key === key ? previewed.data : null;

  const previewMutation = useMutation({
    mutationFn: async (request: { key: string; body: typeof body }) => ({
      key: request.key,
      data: await api.post<VideoPreview>(`/api/courses/${courseId}/videos/preview`, request.body),
    }),
    onSuccess: setPreviewed,
  });
  const stage = useMutation({
    mutationFn: () => api.post(`/api/courses/${courseId}/videos/stage`, body),
    onSuccess: () => {
      staged("Videoen er lagt i endringskøen");
      onStaged();
    },
  });
  const aiRef = itemRef(item);
  const prepare = useMutation({
    mutationFn: () => api.post<AiPlan>(`/api/courses/${courseId}/videos/title-suggestion/prepare`, aiRef),
    onSuccess: (data) => {
      setPlan(data);
      if (data.available && !data.needs_confirmation) suggest.mutate();
    },
  });
  const suggest = useMutation({
    mutationFn: () => api.post<AiTitle>(`/api/courses/${courseId}/videos/title-suggestion`, { ...aiRef, confirmed: true }),
    onSuccess: (data) => {
      setPlan(null);
      setAiTitle(data);
    },
  });

  const canSuggest = item.supported && item.proposed.title.source !== "existing" && item.proposed.title.source !== "youtube_metadata";

  if (!item.supported) {
    return (
      <div className="ek-stack" data-gap="6">
        <Alert tone="danger" title="Krever manuell kontroll">
          {item.manual_reason}
        </Alert>
        <KeyValue items={[["Side", item.location], ["Adresse", <code key="src" className="ek-break">{item.src || "–"}</code>]]} />
        <div className="ek-cluster">
          {item.html_url ? <ExternalLink href={item.html_url}>Åpne siden i Canvas</ExternalLink> : null}
          <Button onClick={() => onIgnore(!ignored)}>{ignored ? "Ikke ignorer" : "Ignorer"}</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="ek-stack" data-gap="6">
      <div className="ek-grid" data-cols="2">
        <section className="ek-stack" data-gap="2" aria-labelledby="video-side">
          <h3 id="video-side">Side</h3>
          <KeyValue
            items={[
              ["Modul", item.modules.length ? item.modules.join(", ") : "Ikke i en modul"],
              ["Side", item.object_title],
            ]}
          />
          {item.html_url ? <ExternalLink href={item.html_url}>Åpne siden i Canvas</ExternalLink> : null}
        </section>
        <section className="ek-stack" data-gap="2" aria-labelledby="video-video">
          <h3 id="video-video">Video</h3>
          <KeyValue
            items={[
              ["YouTube-ID", item.video_id],
              ["YouTube-tittel", item.youtube_title ?? "Ikke tilgjengelig"],
            ]}
          />
          {item.metadata_message ? <p className="ek-xs ek-muted">{item.metadata_message}</p> : null}
        </section>
        <section className="ek-stack" data-gap="2" aria-labelledby="video-naa">
          <h3 id="video-naa">Nåværende</h3>
          <KeyValue
            items={[
              ["Størrelse", item.current.size ?? "Ikke angitt"],
              ["Layout", item.current.layout],
              ["iframe-title", item.current.title || "Mangler"],
            ]}
          />
          {item.issues.length ? (
            <ul className="ek-list-reset ek-cluster" data-gap="1" aria-label="Avvik fra standarden">
              {item.issues.map((issue) => (
                <li key={issue.code}>
                  <Badge tone={issue.code === "manual" ? "danger" : "warning"}>{issue.label}</Badge>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
        <section className="ek-stack" data-gap="2" aria-labelledby="video-forslag">
          <h3 id="video-forslag">Foreslått</h3>
          <p className="ek-small">{item.proposed.layout.split(" · ").join(", ")}</p>
          <KeyValue items={[["Foreslått title", chosen ? `«${chosen}»` : "Ingen – title endres ikke"]]} />
          <div>
            <SourceBadge source={chosen ? (source ?? "manual") : null} />
          </div>
          {source === "page_context" && chosen ? (
            <p className="ek-xs ek-muted">Laget ut fra overskriften og sidetittelen. Kontroller at den beskriver videoen.</p>
          ) : null}
          {source === "ai_suggestion" && chosen ? <AiBadge /> : null}
        </section>
      </div>

      {item.manual_reason ? (
        <Alert tone="warning" title="Krever manuell kontroll">
          {item.manual_reason} Title og adresse kan likevel rettes her.
        </Alert>
      ) : null}
      {item.autoplay ? (
        <Alert tone="warning" title="Videoen starter automatisk">
          Adressen inneholder «autoplay=1». EmneKlar beholder det – vurder å fjerne det i Canvas.
        </Alert>
      ) : null}
      {item.queued ? (
        <Alert tone="info" title="Siden har allerede en endring i køen">
          Forslaget bygger videre på den endringen, så begge gjennomføres samtidig.
        </Alert>
      ) : null}

      <div className="ek-stack" data-gap="2">
        <div className="ek-cluster">
          <Button icon={<Pencil aria-hidden="true" />} onClick={() => setEditing((v) => !v)} aria-expanded={editing}>
            Rediger title
          </Button>
          {canSuggest && aiConfigured ? (
            <Button icon={<Sparkles aria-hidden="true" />} onClick={() => prepare.mutate()} loading={prepare.isPending || suggest.isPending}>
              Foreslå title med KI
            </Button>
          ) : null}
        </div>
        {canSuggest && !aiConfigured ? <AiNotConfigured what="KI-forslag til videotittel" /> : null}
        {editing ? (
          <TextField
            label="iframe-title"
            hint="Kort og beskrivende, for eksempel «Video: Introduksjon til kildekritikk». Ikke bare «Video» eller «YouTube»."
            value={title}
            maxLength={200}
            onChange={(e) => {
              setTitle(e.target.value);
              setSource("manual");
            }}
          />
        ) : null}
        {plan ? (
          <AiConsent plan={plan} onCancel={() => setPlan(null)} onConfirm={() => suggest.mutate()} loading={suggest.isPending}
            confirmLabel="Send og foreslå" />
        ) : null}
        {prepare.error || suggest.error ? (
          <Alert tone="danger" role="alert" title="Kunne ikke lage KI-forslag">
            {((prepare.error ?? suggest.error) as Error).message}
          </Alert>
        ) : null}
        {aiTitle ? (
          <div className="ek-card ek-card--tone ek-card--compact" data-tone="violet">
            <div className="ek-stack" data-gap="2">
              <AiBadge />
              <p>«{aiTitle.title}»</p>
              <div className="ek-cluster">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    setTitle(aiTitle.title);
                    setSource("ai_suggestion");
                  }}
                >
                  Bruk forslaget
                </Button>
                <span className="ek-xs ek-muted">
                  {aiTitle.model} · {aiTitle.provider}
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {previewMutation.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke lage forhåndsvisning">
          {(previewMutation.error as Error).message}
        </Alert>
      ) : null}
      {stage.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke legge endringen i kø">
          {(stage.error as Error).message}
        </Alert>
      ) : null}

      <div className="ek-stack" data-gap="2">
        <div className="ek-cluster">
          <Button icon={<Eye aria-hidden="true" />} onClick={() => previewMutation.mutate({ key, body })} loading={previewMutation.isPending}>
            Forhåndsvis
          </Button>
          <Button
            variant="primary"
            onClick={() => stage.mutate()}
            loading={stage.isPending}
            disabled={!preview || preview.no_change}
            title={!preview ? "Forhåndsvis først" : preview.no_change ? "Ingen endring nødvendig" : undefined}
          >
            Godkjenn
          </Button>
          <Button onClick={() => onIgnore(!ignored)}>{ignored ? "Ikke ignorer" : "Ignorer"}</Button>
        </div>
        <p className="ek-xs ek-muted">
          «Godkjenn» legger endringen i endringskøen. «Ignorer» skjuler videoen fra listen og masse-standardiseringen til
          neste skanning.
        </p>
      </div>

      {preview ? <PreviewPanel preview={preview} device={device} onDevice={setDevice} label={item.object_title} /> : null}
    </div>
  );
}

function PreviewPanel({
  preview,
  device,
  onDevice,
  label,
}: {
  preview: VideoPreview;
  device: PreviewDevice;
  onDevice: (device: PreviewDevice) => void;
  label: string;
}) {
  const height = { desktop: 600, tablet: 480, mobile: 320 }[device];
  return (
    <section className="ek-stack" data-gap="4" aria-labelledby="video-forhandsvisning">
      <h3 id="video-forhandsvisning">Forhåndsvisning</h3>
      {preview.no_change ? (
        <Alert tone="success" title="Ingen endring nødvendig">
          Videoen følger allerede standarden med disse valgene.
        </Alert>
      ) : (
        <div className="ek-cluster">
          <Badge tone="info">{preview.layout}</Badge>
          {preview.title ? <Badge tone="neutral">title: «{preview.title}»</Badge> : null}
          {preview.title_source ? <SourceBadge source={preview.title_source} /> : null}
          {preview.existing_change_id ? <Badge tone="info">Slås sammen med en annen endring på samme side</Badge> : null}
        </div>
      )}
      <p className="ek-xs ek-muted">
        Videoen vises som en grå flate i forhåndsvisningen – ingenting lastes fra YouTube.
      </p>
      <div className="ek-cluster" role="group" aria-label="Visning">
        {(["desktop", "tablet", "mobile"] as PreviewDevice[]).map((d) => (
          <Button key={d} size="sm" variant={device === d ? "primary" : "secondary"} aria-pressed={device === d} onClick={() => onDevice(d)}>
            {{ desktop: "PC", tablet: "Nettbrett", mobile: "Mobil" }[d]}
          </Button>
        ))}
      </div>
      <div className="ek-stack" data-gap="2">
        <h4>Før</h4>
        <HtmlPreview html={preview.before_preview} title={`Før: ${label}`} device={device} minHeight={height} />
      </div>
      {!preview.no_change ? (
        <div className="ek-stack" data-gap="2">
          <h4>Etter</h4>
          <HtmlPreview html={preview.after_preview} title={`Etter: ${label}`} device={device} minHeight={height} />
        </div>
      ) : null}
      <DiffView before={preview.before_display} after={preview.after_display} />
    </section>
  );
}

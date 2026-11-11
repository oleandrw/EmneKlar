// Oversikt: status per area, recommended next steps, recent activity, open findings per area and
// the course content. Every number is a count of real findings or real course content; each finding has exactly one
// class, so the figures never overlap. The time of the analysis is shown once at the top, and areas whose results come
// from another (older, or several) analysis say so.
import { useQuery } from "@tanstack/react-query";
import {
  Accessibility,
  ArrowRight,
  Ban,
  Check,
  ChartColumnBig,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  CircleX,
  ClipboardList,
  Clock,
  Cog,
  Eye,
  EyeOff,
  FileCheck,
  FileText,
  Film,
  FlaskConical,
  Folder,
  Layers,
  Link2,
  ListChecks,
  ListTree,
  LoaderCircle,
  MessagesSquare,
  Network,
  PencilLine,
  Play,
  SquareCheckBig,
  TriangleAlert,
  Undo2,
  Video,
} from "lucide-react";
import { useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDate, formatNumber, formatShortWhen, formatTime } from "../../core/format";
import { CLASSIFICATION, DOMAIN_TONE } from "../../core/labels";
import { useSession } from "../../core/session";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import {
  ActionList,
  ActionRow,
  ActivityList,
  Alert,
  BarChart,
  Card,
  Disclosure,
  EmptyState,
  PageHeader,
  Spinner,
  StatList,
  StatTile,
  StatusCard,
  ToggleChips,
  type ActivityEntry,
  type StatusMetric,
  type Tone,
} from "../../design-system";
import {
  accessibilityRest,
  activityMeta,
  activityStatus,
  analysisLine,
  contentQualityRest,
  count,
  coverageDetails,
  coverageLine,
  CQ_DEAD,
  CQ_MEDIA,
  quizAffected,
  ruleCount,
  structureRest,
  total,
  type ActivityItem,
  type ActivityStatus,
  type DomainCard,
  type DomainKey,
  type Overview,
  type Step,
} from "./model";
import { useResultsFreshness } from "../analysis/AnalysisStatus";

/** Icon and colour for each kind of recommended step (keys from the overview API, which also gives the action). */
const STEP_STYLE: Record<string, { icon: ReactNode; tone: Tone }> = {
  "uu-violations": { icon: <CircleAlert />, tone: "danger" },
  "uu-likely": { icon: <TriangleAlert />, tone: "warning" },
  "uu-manual": { icon: <Eye />, tone: "violet" },
  "dead-links": { icon: <Link2 />, tone: "warning" },
  media: { icon: <Video />, tone: "warning" },
  placement: { icon: <Network />, tone: "teal" },
  quiz: { icon: <ListChecks />, tone: "orange" },
  changes: { icon: <CircleCheck />, tone: "success" },
};

/** One colour rule for every card: red = confirmed errors (avvik, døde lenker), orange = to review or check, blue =
 * suggestions. StatusCard mutes every 0, whatever its class – a red zero would be an alarm about nothing. Counts that
 * are not a class of findings (affected quiz questions) keep the ordinary text colour. */
const FIGURE_TONE = {
  error: "critical",
  check: "warning",
  suggestion: "info",
  count: "neutral",
} as const satisfies Record<string, StatusMetric["tone"]>;
const n = formatNumber;

/** «Hele emnet · 6. nov. kl. 15.42»: breaks only between the parts, never inside a date. */
function Coverage({ text }: { text: string | null }) {
  if (!text) return null;
  const parts = text.split(" · ");
  return (
    <>
      {parts.map((part, i) => (
        <span key={part}>
          {i > 0 ? " · " : null}
          <span className="ek-nowrap">{part}</span>
        </span>
      ))}
    </>
  );
}

/** The lines for one area under «Detaljer og dekning per område» – nothing when there is nothing to add. */
function Details({ lines }: { lines: (ReactNode | null | undefined)[] }) {
  const shown = lines.filter((p) => Boolean(p));
  return shown.length ? <ul>{shown.map((p, i) => <li key={typeof p === "string" ? p : i}>{p}</li>)}</ul> : null;
}

const AREAS: { key: DomainKey; title: string }[] = [
  { key: "accessibility", title: "Universell utforming" },
  { key: "content_quality", title: "Innholdskvalitet" },
  { key: "structure", title: "Emnestruktur" },
  { key: "quiz", title: "Quiz" },
];

/** The smaller line on a card: «12 sannsynlige avvik» (a zero is muted). */
function secondary(value: number, one: string, many: string, tone: StatusMetric["tone"]) {
  return { text: `${n(value)} ${value === 1 ? one : many}`, tone: value === 0 ? ("zero" as const) : tone };
}

/** «2 quizer og 3 spørsmål med funn» – from the counts the overview API gives (or the old total, described exactly). */
function quizAffectedText(card: DomainCard): string {
  const parts = quizAffected(card);
  if (parts.length === 1) return `${n(parts[0].value)} ${parts[0].label}`;
  const [quizzes, questions] = parts;
  // Non-breaking spaces: on a narrow card it breaks only after «og» («1 quiz og / 2 spørsmål med funn»).
  return `${n(quizzes.value)}\u00a0${quizzes.value === 1 ? "quiz" : "quizer"} og ${n(questions.value)}\u00a0spørsmål\u00a0med\u00a0funn`;
}

/** What the figures leave out, per area – the lines that used to be behind each card's «Vis detaljer». */
function areaDetails(key: DomainKey, card: DomainCard, { dead, media }: { dead: number; media: number }): (string | null)[] {
  switch (key) {
    case "accessibility":
      return [`${total(card.total, "åpent funn", "åpne funn")} i alt`, accessibilityRest(card)];
    case "content_quality":
      // Dead links are addresses (as in the Lenker tab), and one address can be several findings: «funn om», not «hvorav».
      return [`${total(card.total, "åpent funn", "åpne funn")} i alt, blant dem funn om ${n(dead)} ${dead === 1 ? "død lenke" : "døde lenker"} og ${n(media)} ${media === 1 ? "utilgjengelig video" : "utilgjengelige videoer"}`,
        contentQualityRest(card)];
    case "structure":
      return [[`${total(card.total, "forslag", "forslag")} i alt`, structureRest(card)].filter(Boolean).join(" ")];
    default:
      return ["Mulige feil i fasit, svaralternativer og duplikater, også fra KI-vurderingen – samme tall som «åpne funn» i Quizassistenten."];
  }
}

/** The tile says what kind of activity it is; the status mark says how it went (text + icon + colour). */
const ACTIVITY_TYPE: Record<ActivityItem["type"], { icon: ReactNode; tone: Tone }> = {
  analysis: { icon: <ChartColumnBig />, tone: "info" },
  change: { icon: <PencilLine />, tone: "teal" },
  job: { icon: <Cog />, tone: "neutral" },
};
const STATUS_ICON: Record<ActivityStatus["kind"], ReactNode> = {
  completed: <CircleCheck />,
  failed: <CircleX />,
  stopped: <Ban />,
  running: <LoaderCircle />,
  waiting: <Clock />,
  conflict: <TriangleAlert />,
  undone: <Undo2 />,
  not_sent: <FlaskConical />,
  other: <CircleHelp />,
};

function activityEntry(a: ActivityItem, i: number): ActivityEntry {
  const type = ACTIVITY_TYPE[a.type] ?? ACTIVITY_TYPE.job;
  const status = activityStatus(a);
  return {
    key: `${a.type}-${a.time ?? ""}-${i}`,
    icon: type.icon,
    tone: type.tone,
    title: a.title,
    status: { label: status.label, tone: status.tone, icon: STATUS_ICON[status.kind] },
    meta: activityMeta(a) ?? undefined,
    date: a.time ? formatDate(a.time) : undefined,
    time: a.time ? formatTime(a.time) : undefined,
  };
}

function StepRow({ step, featured }: { step: Step; featured?: boolean }) {
  const ui = useUi();
  const style = STEP_STYLE[step.key] ?? { icon: <ArrowRight />, tone: step.tone };
  return (
    <ActionRow icon={style.icon} tone={style.tone} title={step.title} description={step.description}
      actionLabel={step.action} to={step.path ?? undefined} onClick={step.path ? undefined : ui.openChanges}
      featured={featured} />
  );
}

/** One recommended step first, up to two more, the rest behind «Se alle anbefalinger». */
function NextSteps({ steps, anyAnalysis }: { steps: Step[]; anyAnalysis: boolean }) {
  if (steps.length === 0) {
    return (
      <p className="ek-muted">
        {anyAnalysis ? "Ingen åpne funn med høy prioritet i siste analyse." : "Kjør en analyse for å få anbefalinger."}
      </p>
    );
  }
  const [first, ...others] = steps;
  const more = others.slice(2);
  return (
    <div className="ek-stack" data-gap="3">
      <ActionList label="Anbefalt neste steg">
        <StepRow step={first} featured />
        {others.slice(0, 2).map((step) => <StepRow key={step.key} step={step} />)}
      </ActionList>
      {more.length ? (
        <Disclosure summary={`Se alle anbefalinger (${more.length} til)`}>
          <ActionList label="Flere anbefalinger">
            {more.map((step) => <StepRow key={step.key} step={step} />)}
          </ActionList>
        </Disclosure>
      ) : null}
      <Disclosure summary="Hvordan prioriteres anbefalingene?">
        <p className="ek-small ek-muted">
          Rekkefølgen følger hvor sikkert funnet er (avvik før sannsynlige avvik), hvor alvorlig det er og hvor konkret det
          kan følges opp – ikke hvor mange funn det er.
        </p>
      </Disclosure>
    </div>
  );
}

/** «Åpne funn per område»: which classes the chart shows. Confirmed violations and «Bør vurderes» by default – many
 *  improvement suggestions alone should not make an area look like the most serious problem. */
type ChartClass = "violation" | "likely_violation" | "should_review" | "improvement" | "manual_check";
const CHART_CLASSES: { key: ChartClass; label: string; color: string }[] = [
  // Every area is in the chart, so the confirmed class is «avvik» (universal design) and «feil» (the others).
  { key: "violation", label: "Bekreftede avvik og feil", color: "var(--chart-violation)" },
  { key: "likely_violation", label: "Sannsynlige avvik og feil", color: "var(--chart-likely)" },
  { key: "should_review", label: CLASSIFICATION.should_review.label, color: "var(--chart-review)" },
  { key: "improvement", label: CLASSIFICATION.improvement.label, color: "var(--chart-improvement)" },
  { key: "manual_check", label: CLASSIFICATION.manual_check.label, color: "var(--chart-manual)" },
];
const CHART_DEFAULT: ChartClass[] = ["violation", "should_review"];
/** At most this many events on the overview, newest first; the rest are in the job history and the change log. */
const ACTIVITY_SHOWN = 4;

function FindingsChart({ cards, anyAnalysis }: { cards: DomainCard[]; anyAnalysis: boolean }) {
  const [shown, setShown] = useState<ChartClass[]>(CHART_DEFAULT);
  const toggle = (key: ChartClass) =>
    setShown((current) => (current.includes(key) ? current.filter((k) => k !== key) : [...current, key]));
  const series = CHART_CLASSES.filter((c) => shown.includes(c.key)).map((c) => ({
    key: c.key, label: c.label, color: c.color, values: cards.map((card) => count(card, c.key)),
  }));
  return (
    <div className="ek-stack" data-gap="4">
      <ToggleChips label="Vis i diagrammet" showLabel values={shown} onToggle={toggle}
        options={CHART_CLASSES.map((c) => ({
          value: c.key,
          label: c.label,
          icon: shown.includes(c.key) ? <Check aria-hidden="true" />
            : <span className="ek-chart__swatch" style={{ "--swatch": c.color } as CSSProperties} aria-hidden="true" />,
        }))} />
      {series.length === 0 ? (
        <p className="ek-chart__empty">Velg minst én kategori for å vise diagrammet.</p>
      ) : (
        <BarChart
          label={`Åpne funn per område: ${series.map((x) => x.label.toLowerCase()).join(", ")}`}
          categoryHeader="Område"
          emptyText={anyAnalysis ? "Ingen åpne funn i de valgte kategoriene." : "Diagrammet vises etter første analyse."}
          categories={[
            { key: "accessibility", label: "Universell utforming", shortLabel: "UU" },
            { key: "content_quality", label: "Innholdskvalitet", shortLabel: "Innhold" },
            { key: "structure", label: "Emnestruktur", shortLabel: "Struktur" },
            { key: "quiz", label: "Quiz", shortLabel: "Quiz" },
          ]}
          series={series}
        />
      )}
    </div>
  );
}

export function OverviewPage() {
  usePageTitle("Emneoversikt");
  const session = useSession();
  const { courseId } = useCurrentCourse();
  const overview = useQuery({
    queryKey: ["overview", courseId],
    queryFn: () => api.get<Overview>(`/api/courses/${courseId}/overview`),
    enabled: Boolean(courseId),
  });
  const freshness = useResultsFreshness(undefined, overview.data?.analysis?.time ?? null);

  if (!courseId) {
    return (
      <>
        <PageHeader title="Emneoversikt" />
        <EmptyState title="Velg et emne">Velg emnet du vil jobbe med i emnevelgeren øverst på siden.</EmptyState>
      </>
    );
  }
  const data = overview.data;
  const c = data?.cards;
  const cards = c ? [c.accessibility, c.content_quality, c.structure, c.quiz] : [];
  const anyAnalysis = cards.some((card) => card.analyzed);
  const newest = data?.analysis ?? null;
  // The «Fungerer ikke» total of Innholdskvalitet → Lenker (older servers: the dead link findings).
  const dead = c ? (c.content_quality.dead_links ?? ruleCount(c.content_quality, ...CQ_DEAD)) : 0;
  const media = c ? ruleCount(c.content_quality, ...CQ_MEDIA) : 0;
  const quizTotal = c ? (c.quiz.total_with_ai ?? c.quiz.total) : 0;
  const quizEnabled = session.flags?.quiz_assistant !== false;
  const activity = data?.activity ?? [];

  return (
    <>
      <PageHeader
        title="Emneoversikt"
        description="Samlet status for emnet og anbefalte neste steg."
        meta={freshness ?? analysisLine(newest, { full: data?.full_analysis ?? null, cards, quizEnabled })}
      />
      {overview.isPending ? <Spinner label="Henter oversikt …" /> : null}
      {overview.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke hente oversikten">
          {(overview.error as Error).message}
        </Alert>
      ) : null}
      {data && c ? (
        <div className="ek-overview">
          {!anyAnalysis ? (
            <EmptyState
              icon={<Play aria-hidden="true" />}
              title="Kom i gang med første analyse"
            >
              Start med «Analyser hele emnet» øverst til høyre. EmneKlar leser emnet fra Canvas og finner forbedringer innen
              universell utforming, innholdskvalitet, struktur og quiz. Analysen endrer ingenting i Canvas, og rettinger
              publiseres først når du godkjenner dem (med mindre du velger automatisk innsetting i KI-bildeassistenten).
            </EmptyState>
          ) : null}

          <section aria-labelledby="status-per-omrade">
            <h2 id="status-per-omrade" className="ek-visually-hidden">
              Status per område
            </h2>
            <div className="ek-grid ek-area-grid" data-cols="4" data-gap="6">
              <StatusCard
                title="Universell utforming"
                icon={<Accessibility />}
                tone={DOMAIN_TONE.accessibility}
                to="/universell-utforming"
                empty={c.accessibility.analyzed ? undefined : "Ikke analysert ennå"}
                metric={{ value: count(c.accessibility, "violation"), label: "bekreftede avvik", tone: FIGURE_TONE.error }}
                secondary={secondary(count(c.accessibility, "likely_violation"), "sannsynlig avvik", "sannsynlige avvik", FIGURE_TONE.check)}
                description={coverageLine(c.accessibility)}
              />
              <StatusCard
                title="Innholdskvalitet"
                icon={<FileCheck />}
                tone={DOMAIN_TONE.content_quality}
                to="/innholdskvalitet"
                empty={c.content_quality.analyzed ? undefined : "Ikke analysert ennå"}
                metric={{ value: dead, label: dead === 1 ? "død lenke" : "døde lenker", tone: FIGURE_TONE.error }}
                secondary={secondary(media, "utilgjengelig video", "utilgjengelige videoer", FIGURE_TONE.check)}
                description={coverageLine(c.content_quality)}
              />
              <StatusCard
                title="Emnestruktur"
                icon={<ListTree />}
                tone={DOMAIN_TONE.structure}
                to="/emnestruktur"
                empty={c.structure.analyzed ? undefined : "Ikke analysert ennå"}
                metric={{ value: count(c.structure, "should_review"), label: "bør vurderes", tone: FIGURE_TONE.check }}
                secondary={secondary(count(c.structure, "improvement"), "forbedringsforslag", "forbedringsforslag", FIGURE_TONE.suggestion)}
                description={coverageLine(c.structure)}
              />
              <StatusCard
                title="Quiz"
                icon={<ListChecks />}
                tone={DOMAIN_TONE.quiz}
                to="/quizassistent"
                empty={c.quiz.analyzed ? undefined : "Ikke analysert ennå"}
                metric={{ value: quizTotal, label: quizTotal === 1 ? "mulig feil" : "mulige feil", tone: FIGURE_TONE.check }}
                secondary={{ text: quizAffectedText(c.quiz), tone: FIGURE_TONE.count }}
                description={coverageLine(c.quiz)}
              />
            </div>
          </section>

          <div className="ek-overview__notes">
            <Disclosure summary="Detaljer og dekning per område">
              <dl className="ek-overview__details">
                {AREAS.map(({ key, title }) => {
                  const area = c[key];
                  return (
                    <div key={key}>
                      <dt>{title}</dt>
                      <dd>
                        {area.analyzed ? (
                          <Details lines={[
                            <Coverage key="coverage" text={coverageLine(area)} />,
                            ...areaDetails(key, area, { dead, media }),
                            coverageDetails(area),
                          ]} />
                        ) : "Ikke analysert ennå."}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </Disclosure>
            <Disclosure summary="Hva betyr tallene?">
              <div className="ek-stack ek-small ek-muted" data-gap="2">
                <p>
                  Tallene er åpne funn, også de som ligger i endringskøen. Hvert funn har én klasse, så tallene overlapper
                  ikke. «Bekreftede avvik» er brudd som er påvist; «sannsynlige avvik» er sterke indikasjoner som må
                  kontrolleres. Automatiske kontroller kan ikke bevise samsvar med regelverket.
                </p>
                <p>
                  Det store tallet er det viktigste for området; linjen under er færre sikre, mindre alvorlige eller en annen
                  type problem. Fargene følger klassen: rødt for bekreftede feil, oransje for det som bør vurderes eller
                  kontrolleres, blått for forbedringsforslag. Tallet 0 vises alltid dempet. Linjen nederst i hvert kort har
                  områdets farge og er pynt, ikke fremdrift. Hvor gamle tallene er, og om de er satt sammen av flere
                  analyser, står under «Detaljer og dekning per område».
                </p>
              </div>
            </Disclosure>
          </div>

          <div className="ek-overview__grid">
            <Card title="Anbefalt neste steg">
              <NextSteps steps={data.next_steps} anyAnalysis={anyAnalysis} />
            </Card>
            <Card title="Siste analyser og aktivitet" footer={activity.length ? (
              <p className="ek-small">
                Se all aktivitet: <Link to="/rapporter#jobbhistorikk">Jobbhistorikk</Link>
                {" · "}
                <Link to="/canvas-verktoy/endringslogg">Endringslogg</Link>
              </p>
            ) : undefined}>
              {activity.length === 0 ? (
                <p className="ek-muted">Ingen aktivitet ennå.</p>
              ) : (
                <div className="ek-overview__body">
                  <ActivityList label="Siste analyser og endringer" items={activity.slice(0, ACTIVITY_SHOWN).map(activityEntry)} />
                </div>
              )}
            </Card>
            <Card title="Åpne funn per område"
              description="Antall åpne funn i de valgte kategoriene – ikke en samlet alvorlighetsgrad.">
              <FindingsChart cards={cards} anyAnalysis={anyAnalysis} />
            </Card>
            <Card
              title="Innhold i emnet"
              description={data.stats
                ? data.stats.run_id === newest?.id
                  ? "Slik emnet så ut ved siste analyse."
                  : `Slik emnet så ut ved analysen ${formatShortWhen(data.stats.analysed_at)}.`
                : undefined}
            >
              {data.stats ? (
                <div className="ek-stack" data-gap="3">
                  <StatList label="Innhold i emnet">
                    <StatTile icon={<FileText />} tone="info" value={Number(data.stats.pages)} label="Sider" />
                    <StatTile icon={<Layers />} tone="teal" value={Number(data.stats.modules)} label="Moduler" />
                    <StatTile icon={<ClipboardList />} tone="orange" value={Number(data.stats.assignments)} label="Oppgaver" />
                    <StatTile icon={<SquareCheckBig />} tone="success" value={Number(data.stats.quizzes)} label="Quizer" />
                    <StatTile icon={<MessagesSquare />} tone="violet" value={Number(data.stats.discussions)} label="Diskusjoner" />
                    <StatTile icon={<Folder />} tone="neutral" value={Number(data.stats.files)} label="Filer" />
                    <StatTile icon={<Film />} tone="info" value={Number(data.stats.media)} label="Video og lyd" />
                    <StatTile icon={<EyeOff />} tone="neutral" value={Number(data.stats.unpublished)} label="Upublisert innhold" />
                  </StatList>
                  <p className="ek-xs ek-muted">
                    «Upublisert innhold» er sider, oppgaver, quizer og diskusjoner som ikke er publisert for studentene. De
                    er allerede med i tallene over, så tallene skal ikke legges sammen.
                  </p>
                </div>
              ) : (
                <p className="ek-muted">Statistikk vises etter første analyse.</p>
              )}
            </Card>
          </div>
        </div>
      ) : null}
    </>
  );
}

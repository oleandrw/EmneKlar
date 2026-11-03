// Oversikt: status per area, recommended next steps, recent activity, open findings per area and
// the course content. Every number is a count of real findings or real course content.
import { useQuery } from "@tanstack/react-query";
import {
  Accessibility,
  ArrowRight,
  ChartColumnBig,
  CircleAlert,
  CircleCheck,
  CircleX,
  ClipboardList,
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
  MessagesSquare,
  Network,
  Play,
  SquareCheckBig,
  Undo2,
  Video,
} from "lucide-react";
import type { ReactNode } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDate, formatDateTime, formatTime, relativeTime } from "../../core/format";
import { CLASSIFICATION, DOMAIN_TONE } from "../../core/labels";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import {
  ActionList,
  ActionRow,
  ActivityList,
  Alert,
  BarChart,
  Button,
  Card,
  EmptyState,
  MoreLink,
  PageHeader,
  Spinner,
  StatList,
  StatTile,
  StatusCard,
  type ActivityEntry,
  type StatusMetric,
  type Tone,
} from "../../design-system";

type DomainKey = "accessibility" | "content_quality" | "structure" | "quiz";

interface DomainCard {
  domain: string;
  analyzed: boolean;
  last_run: string | null;
  total: number;
  by_classification: Record<string, number>;
  by_rule: Record<string, number>;
  serious: number;
  objects: number;
}

interface Overview {
  cards: Record<DomainKey, DomainCard>;
  next_steps: { key: string; title: string; description: string; path: string | null; tone: Tone; count: number }[];
  activity: { type: string; time: string | null; title: string; status: string; dry_run?: boolean }[];
  stats: Record<string, number | string> | null;
  pending_changes: number;
}

const ACTIVITY_STATUS: Record<string, string> = {
  completed: "Fullført",
  failed: "Feilet",
  cancelled: "Avbrutt",
  interrupted: "Avbrutt",
  running: "Pågår",
  apply: "Endring gjennomført",
  undo: "Endring angret",
  dry_run: "Dry run (ikke sendt)",
  conflict: "Konflikt",
};

/** Icon, colour and call to action for each kind of recommended step (keys from the overview API). */
const STEP_STYLE: Record<string, { icon: ReactNode; tone: Tone; action: string }> = {
  "uu-serious": { icon: <CircleAlert />, tone: "danger", action: "Gå til UU" },
  "uu-manual": { icon: <Eye />, tone: "violet", action: "Se kontrollene" },
  "dead-links": { icon: <Link2 />, tone: "warning", action: "Se lenker" },
  media: { icon: <Video />, tone: "warning", action: "Se videoer" },
  placement: { icon: <Network />, tone: "teal", action: "Se forslag" },
  quiz: { icon: <ListChecks />, tone: "orange", action: "Gå til quiz" },
  changes: { icon: <CircleCheck />, tone: "success", action: "Åpne endringskøen" },
};

const count = (card: DomainCard, ...classes: string[]) => classes.reduce((sum, c) => sum + (card.by_classification[c] ?? 0), 0);
const ruleCount = (card: DomainCard, ...rules: string[]) => rules.reduce((sum, r) => sum + (card.by_rule[r] ?? 0), 0);
/** Red and amber only when there is something to see – a red zero would be an alarm about nothing. */
const tone = (value: number, when: StatusMetric["tone"]): StatusMetric["tone"] => (value > 0 ? when : "neutral");

function latest(cards: DomainCard[]): string | null {
  const times = cards.map((c) => c.last_run).filter((t): t is string => Boolean(t)).sort();
  return times.length ? times[times.length - 1] : null;
}

/** Shown on a card only when that area was analysed at another time than the newest analysis. */
function analysedNote(card: DomainCard, newest: string | null): string | null {
  if (!card.last_run || !newest) return null;
  const apart = Math.abs(new Date(newest).getTime() - new Date(card.last_run).getTime());
  return apart > 10 * 60 * 1000 ? `Analysert ${relativeTime(card.last_run)}` : null;
}

function foot(...parts: (string | null)[]): ReactNode {
  const shown = parts.filter((p): p is string => Boolean(p));
  return shown.length ? shown.join(" · ") : undefined;
}

function activityEntry(a: Overview["activity"][number], i: number): ActivityEntry {
  const status = a.dry_run ? "dry_run" : a.status;
  let icon: ReactNode = <ChartColumnBig />;
  let entryTone: Tone = "info";
  if (a.type === "change") {
    icon = <CircleCheck />;
    entryTone = "success";
  }
  if (status === "dry_run") {
    icon = <FlaskConical />;
    entryTone = "warning";
  } else if (status === "undo") {
    icon = <Undo2 />;
    entryTone = "orange";
  } else if (status === "failed" || status === "conflict") {
    icon = <CircleX />;
    entryTone = "danger";
  } else if (status === "cancelled" || status === "interrupted") {
    entryTone = "neutral";
  }
  return {
    key: `${a.type}-${a.time ?? ""}-${i}`,
    icon,
    tone: entryTone,
    title: a.title,
    meta: ACTIVITY_STATUS[status] ?? status,
    date: a.time ? formatDate(a.time) : undefined,
    time: a.time ? formatTime(a.time) : undefined,
  };
}

export function OverviewPage() {
  usePageTitle("Emneoversikt");
  const ui = useUi();
  const { courseId } = useCurrentCourse();
  const overview = useQuery({
    queryKey: ["overview", courseId],
    queryFn: () => api.get<Overview>(`/api/courses/${courseId}/overview`),
    enabled: Boolean(courseId),
  });

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
  const newest = latest(cards);

  return (
    <>
      <PageHeader
        title="Emneoversikt"
        description="Samlet status for emnet og anbefalte neste steg."
        meta={newest ? `Sist analysert: ${formatDateTime(newest)}` : undefined}
      />
      {overview.isPending ? <Spinner label="Henter oversikt …" /> : null}
      {overview.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke hente oversikten">
          {(overview.error as Error).message}
        </Alert>
      ) : null}
      {data && c ? (
        <div className="ek-stack" data-gap="6">
          {!anyAnalysis ? (
            <EmptyState
              icon={<Play aria-hidden="true" />}
              title="Kom i gang med første analyse"
              actions={
                <Button variant="primary" size="lg" icon={<Play aria-hidden="true" />} onClick={() => ui.openAnalysis()}>
                  Kjør ny analyse
                </Button>
              }
            >
              EmneKlar leser emnet fra Canvas og finner forbedringer innen universell utforming, innholdskvalitet, struktur og
              quiz. Ingenting endres i Canvas før du selv godkjenner det.
            </EmptyState>
          ) : null}

          <section aria-labelledby="status-per-omrade" className="ek-stack" data-gap="3">
            <h2 id="status-per-omrade" className="ek-visually-hidden">
              Status per område
            </h2>
            <div className="ek-grid" data-cols="4" data-gap="5">
              <StatusCard
                title="Universell utforming"
                icon={<Accessibility />}
                tone={DOMAIN_TONE.accessibility}
                to="/universell-utforming"
                empty={c.accessibility.analyzed ? undefined : "Ikke analysert ennå"}
                metrics={[
                  { value: count(c.accessibility, "violation", "likely_violation"), label: "avvik / sannsynlige avvik",
                    tone: tone(count(c.accessibility, "violation", "likely_violation"), "critical") },
                  { value: count(c.accessibility, "should_review"), label: "bør vurderes",
                    tone: tone(count(c.accessibility, "should_review"), "warning") },
                ]}
                footnote={foot(
                  count(c.accessibility, "manual_check") ? `${count(c.accessibility, "manual_check")} krever manuell kontroll` : null,
                  analysedNote(c.accessibility, newest),
                )}
              />
              <StatusCard
                title="Innholdskvalitet"
                icon={<FileCheck />}
                tone={DOMAIN_TONE.content_quality}
                to="/innholdskvalitet"
                empty={c.content_quality.analyzed ? undefined : "Ikke analysert ennå"}
                metrics={[
                  { value: ruleCount(c.content_quality, "CQ-LINK-DEAD", "CQ-LINK-INTERNAL-MISSING"), label: "døde lenker",
                    tone: tone(ruleCount(c.content_quality, "CQ-LINK-DEAD", "CQ-LINK-INTERNAL-MISSING"), "critical") },
                  { value: ruleCount(c.content_quality, "CQ-MEDIA-UNAVAILABLE"), label: "utilgjengelige videoer",
                    tone: tone(ruleCount(c.content_quality, "CQ-MEDIA-UNAVAILABLE"), "warning") },
                ]}
                footnote={foot(`${c.content_quality.total} funn totalt`, analysedNote(c.content_quality, newest))}
              />
              <StatusCard
                title="Emnestruktur"
                icon={<ListTree />}
                tone={DOMAIN_TONE.structure}
                to="/emnestruktur"
                empty={c.structure.analyzed ? undefined : "Ikke analysert ennå"}
                metrics={[
                  { value: c.structure.total, label: "forslag", tone: tone(c.structure.total, "info") },
                  { value: count(c.structure, "should_review"), label: "bør vurderes",
                    tone: tone(count(c.structure, "should_review"), "warning") },
                ]}
                footnote={foot(analysedNote(c.structure, newest))}
              />
              <StatusCard
                title="Quiz"
                icon={<ListChecks />}
                tone={DOMAIN_TONE.quiz}
                to="/quizassistent"
                empty={c.quiz.analyzed ? undefined : "Ikke analysert ennå"}
                metrics={[{ value: c.quiz.objects, label: "spørsmål bør kontrolleres", tone: tone(c.quiz.objects, "warning") }]}
                footnote={foot(analysedNote(c.quiz, newest))}
              />
            </div>
            <p className="ek-xs ek-subtle">
              Tallene er åpne funn i siste analyse. Automatiske kontroller kan ikke bevise samsvar med regelverket.
            </p>
          </section>

          <div className="ek-split" data-align="stretch">
            <Card title="Anbefalt neste steg">
              {data.next_steps.length === 0 ? (
                <p className="ek-muted">
                  {anyAnalysis ? "Ingen åpne funn med høy prioritet i siste analyse." : "Kjør en analyse for å få anbefalinger."}
                </p>
              ) : (
                <ActionList label="Anbefalte steg">
                  {data.next_steps.map((step) => {
                    const style = STEP_STYLE[step.key] ?? { icon: <ArrowRight />, tone: step.tone, action: "Åpne" };
                    return (
                      <ActionRow
                        key={step.key}
                        icon={style.icon}
                        tone={style.tone}
                        title={step.title}
                        description={step.description}
                        actionLabel={style.action}
                        to={step.path ?? undefined}
                        onClick={step.path ? undefined : ui.openChanges}
                      />
                    );
                  })}
                </ActionList>
              )}
            </Card>
            <Card title="Siste analyser og aktivitet" actions={<MoreLink to="/canvas-verktoy/endringslogg">Se endringslogg</MoreLink>}>
              {data.activity.length === 0 ? (
                <p className="ek-muted">Ingen aktivitet ennå.</p>
              ) : (
                <ActivityList label="Siste analyser og endringer" items={data.activity.map(activityEntry)} />
              )}
            </Card>
          </div>

          <div className="ek-split" data-align="stretch">
            <Card title="Åpne funn per område" description="Åpne funn i siste analyse, fordelt på klasse.">
              <BarChart
                label="Åpne funn per område og klasse"
                categoryHeader="Område"
                emptyText={anyAnalysis ? "Ingen åpne funn i siste analyse." : "Diagrammet vises etter første analyse."}
                categories={[
                  { key: "accessibility", label: "Universell utforming", shortLabel: "UU" },
                  { key: "content_quality", label: "Innholdskvalitet", shortLabel: "Innhold" },
                  { key: "structure", label: "Emnestruktur", shortLabel: "Struktur" },
                  { key: "quiz", label: "Quiz", shortLabel: "Quiz" },
                ]}
                series={[
                  { key: "violation", label: "Avvik og sannsynlige avvik", color: "var(--chart-violation)",
                    values: cards.map((card) => count(card, "violation", "likely_violation")) },
                  { key: "review", label: CLASSIFICATION.should_review.label, color: "var(--chart-review)",
                    values: cards.map((card) => count(card, "should_review")) },
                  { key: "improvement", label: CLASSIFICATION.improvement.label, color: "var(--chart-improvement)",
                    values: cards.map((card) => count(card, "improvement")) },
                  { key: "manual", label: CLASSIFICATION.manual_check.label, color: "var(--chart-manual)",
                    values: cards.map((card) => count(card, "manual_check")) },
                ]}
              />
            </Card>
            <Card
              title="Innhold i emnet"
              description={data.stats ? `Fra analysen ${formatDateTime(String(data.stats.snapshot_at))}` : undefined}
            >
              {data.stats ? (
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

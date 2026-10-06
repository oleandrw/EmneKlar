import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Play } from "lucide-react";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDateTime, formatNumber, relativeTime } from "../../core/format";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import { Alert, Badge, Button, Card, EmptyState, PageHeader, Section, Spinner, Stat, type Tone } from "../../design-system";

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
  cards: Record<"accessibility" | "content_quality" | "structure" | "quiz", DomainCard>;
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

function Metric({ value, label }: { value: number; label: string }) {
  return (
    <p>
      <span className="ek-strong" style={{ fontSize: "var(--text-xl)" }}>
        {formatNumber(value)}
      </span>{" "}
      <span>{label}</span>
    </p>
  );
}

function DomainCardView({ eyebrow, card, path, children }: { eyebrow: string; card: DomainCard; path: string; children: React.ReactNode }) {
  return (
    <Card eyebrow={eyebrow} headingLevel={3}>
      <div className="ek-stack" data-gap="3">
        {card.analyzed ? children : <p className="ek-muted">Ikke analysert ennå.</p>}
        <p className="ek-xs ek-muted">{card.analyzed ? `Sist analysert ${relativeTime(card.last_run)}` : " "}</p>
        <Link to={path} className="ek-small ek-strong">
          Se {eyebrow.toLowerCase()}
          <ArrowRight aria-hidden="true" size={14} style={{ verticalAlign: "middle", marginLeft: 4 }} />
        </Link>
      </div>
    </Card>
  );
}

export function OverviewPage() {
  usePageTitle("Oversikt");
  const ui = useUi();
  const { courseId, course } = useCurrentCourse();
  const overview = useQuery({
    queryKey: ["overview", courseId],
    queryFn: () => api.get<Overview>(`/api/courses/${courseId}/overview`),
    enabled: Boolean(courseId),
  });

  if (!courseId) {
    return (
      <>
        <PageHeader title="Oversikt" />
        <EmptyState title="Velg et emne">Velg emnet du vil jobbe med i emnevelgeren øverst på siden.</EmptyState>
      </>
    );
  }
  const data = overview.data;
  const anyAnalysis = data ? Object.values(data.cards).some((c) => c.analyzed) : false;
  const c = data?.cards;

  return (
    <>
      <PageHeader
        title="Oversikt"
        eyebrow={course ? `${course.course_code ?? ""} ${course.term_name ? `· ${course.term_name}` : ""}` : undefined}
        description={course?.name}
        actions={
          <Button variant="primary" icon={<Play aria-hidden="true" />} onClick={() => ui.openAnalysis()}>
            Kjør ny analyse
          </Button>
        }
      />
      {overview.isPending ? <Spinner label="Henter oversikt …" /> : null}
      {overview.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke hente oversikten">
          {(overview.error as Error).message}
        </Alert>
      ) : null}
      {data && c ? (
        <div className="ek-stack" data-gap="8">
          {!anyAnalysis ? (
            <EmptyState
              title="Kom i gang med første analyse"
              actions={
                <Button variant="primary" onClick={() => ui.openAnalysis()}>
                  Kjør ny analyse
                </Button>
              }
            >
              EmneKlar leser emnet fra Canvas og finner forbedringer innen universell utforming, innholdskvalitet, struktur og
              quiz. Ingenting endres i Canvas før du selv godkjenner det.
            </EmptyState>
          ) : null}
          <Section title="Status per område" description="Tall er antall åpne funn i siste analyse. Automatiske kontroller kan ikke bevise samsvar.">
            <div className="ek-grid" data-cols="4">
              <DomainCardView eyebrow="Universell utforming" card={c.accessibility} path="/universell-utforming">
                <Metric
                  value={(c.accessibility.by_classification.violation ?? 0) + (c.accessibility.by_classification.likely_violation ?? 0)}
                  label="avvik / sannsynlige avvik"
                />
                <Metric value={c.accessibility.by_classification.should_review ?? 0} label="bør vurderes" />
                <Metric value={c.accessibility.by_classification.manual_check ?? 0} label="krever manuell kontroll" />
              </DomainCardView>
              <DomainCardView eyebrow="Innholdskvalitet" card={c.content_quality} path="/innholdskvalitet">
                <Metric value={(c.content_quality.by_rule["CQ-LINK-DEAD"] ?? 0) + (c.content_quality.by_rule["CQ-LINK-INTERNAL-MISSING"] ?? 0)} label="døde lenker" />
                <Metric value={c.content_quality.by_rule["CQ-MEDIA-UNAVAILABLE"] ?? 0} label="utilgjengelige videoer" />
                <Metric value={c.content_quality.total} label="funn totalt" />
              </DomainCardView>
              <DomainCardView eyebrow="Emnestruktur" card={c.structure} path="/emnestruktur">
                <Metric value={c.structure.total} label="forslag" />
                <Metric value={c.structure.by_classification.should_review ?? 0} label="bør vurderes" />
              </DomainCardView>
              <DomainCardView eyebrow="Quiz" card={c.quiz} path="/quizassistent">
                <Metric value={c.quiz.objects} label="spørsmål bør kontrolleres" />
              </DomainCardView>
            </div>
          </Section>

          <Section title="Anbefalt neste steg">
            {data.next_steps.length === 0 ? (
              <p className="ek-muted">
                {anyAnalysis ? "Ingen åpne funn med høy prioritet i siste analyse." : "Kjør en analyse for å få anbefalinger."}
              </p>
            ) : (
              <ul className="ek-grid ek-list-reset" data-cols="2">
                {data.next_steps.map((step) => (
                  <li key={step.key}>
                    {step.path ? (
                      <Link to={step.path} className="ek-card ek-card--link ek-card--tone" data-tone={step.tone}>
                        <span className="ek-stack" data-gap="1">
                          <span className="ek-strong">{step.title}</span>
                          <span className="ek-small">{step.description}</span>
                        </span>
                      </Link>
                    ) : (
                      <button type="button" className="ek-card ek-card--link ek-card--tone" data-tone={step.tone} onClick={ui.openChanges}>
                        <span className="ek-stack" data-gap="1">
                          <span className="ek-strong">{step.title}</span>
                          <span className="ek-small">{step.description}</span>
                        </span>
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <div className="ek-grid" data-cols="2">
            <Section title="Siste aktivitet">
              {data.activity.length === 0 ? (
                <p className="ek-muted">Ingen aktivitet ennå.</p>
              ) : (
                <ul className="ek-list-reset ek-divider-list">
                  {data.activity.map((a, i) => (
                    <li key={i} className="ek-row">
                      <div className="ek-row__main">
                        <p className="ek-strong">{a.title}</p>
                        <p className="ek-xs ek-muted">{formatDateTime(a.time)}</p>
                      </div>
                      <Badge tone={a.status === "failed" ? "danger" : a.dry_run ? "warning" : "neutral"}>
                        {ACTIVITY_STATUS[a.status] ?? a.status}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
            <Section title="Innhold i emnet" description={data.stats ? `Fra analysen ${formatDateTime(String(data.stats.snapshot_at))}` : undefined}>
              {data.stats ? (
                <div className="ek-grid" data-cols="4">
                  <Stat value={formatNumber(Number(data.stats.modules))} label="Moduler" />
                  <Stat value={formatNumber(Number(data.stats.pages))} label="Sider" />
                  <Stat value={formatNumber(Number(data.stats.assignments))} label="Oppgaver" />
                  <Stat value={formatNumber(Number(data.stats.quizzes))} label="Quizer" />
                  <Stat value={formatNumber(Number(data.stats.discussions))} label="Diskusjoner" />
                  <Stat value={formatNumber(Number(data.stats.files))} label="Filer" />
                  <Stat value={formatNumber(Number(data.stats.unpublished))} label="Upublisert innhold" />
                </div>
              ) : (
                <p className="ek-muted">Statistikk vises etter første analyse.</p>
              )}
            </Section>
          </div>
        </div>
      ) : null}
    </>
  );
}

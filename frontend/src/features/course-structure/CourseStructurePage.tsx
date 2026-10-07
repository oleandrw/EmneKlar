import { useQuery } from "@tanstack/react-query";
import {
  AppWindow,
  ArrowRight,
  BookOpen,
  ClipboardList,
  ExternalLink as ExternalLinkIcon,
  FileText,
  Flag,
  Heading,
  Lightbulb,
  MessagesSquare,
  Paperclip,
  Play,
  Route,
  SquareCheckBig,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDate, formatDateTime } from "../../core/format";
import { useSession } from "../../core/session";
import { HelpLink } from "../../core/HelpLink";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ExternalLink,
  IconTile,
  PageHeader,
  Spinner,
  Tabs,
  type Tone,
} from "../../design-system";
import { FindingsView } from "../findings/FindingsView";

interface StructureItem {
  id: string;
  title: string;
  type: string;
  published: boolean | null;
  indent: number;
  requirement: string | null;
  due_at: string | null;
  url: string | null;
}

interface StructureModule {
  id: string;
  name: string;
  published: boolean | null;
  require_sequential_progress: boolean | null;
  requirement_type: string | null;
  items: StructureItem[];
  journey: string[];
}

interface StructureResponse {
  snapshot_at: string | null;
  modules: StructureModule[];
}

const STEP_TONE: Record<string, Tone> = {
  Les: "info", Innlevering: "orange", Quiz: "success", Diskusjon: "violet", Fil: "neutral",
  "Ekstern ressurs": "teal", Verktøy: "teal",
};
const STEP_ICON: Record<string, LucideIcon> = {
  Les: BookOpen, Innlevering: ClipboardList, Quiz: SquareCheckBig, Diskusjon: MessagesSquare, Fil: Paperclip,
  "Ekstern ressurs": ExternalLinkIcon, Verktøy: AppWindow,
};
const ITEM_TYPE: Record<string, { label: string; plural: string; icon: LucideIcon; tone: Tone }> = {
  Page: { label: "Side", plural: "sider", icon: FileText, tone: "info" },
  Assignment: { label: "Oppgave", plural: "oppgaver", icon: ClipboardList, tone: "orange" },
  Quiz: { label: "Quiz", plural: "quizer", icon: SquareCheckBig, tone: "success" },
  Discussion: { label: "Diskusjon", plural: "diskusjoner", icon: MessagesSquare, tone: "violet" },
  File: { label: "Fil", plural: "filer", icon: Paperclip, tone: "neutral" },
  ExternalUrl: { label: "Ekstern lenke", plural: "eksterne lenker", icon: ExternalLinkIcon, tone: "teal" },
  ExternalTool: { label: "Eksternt verktøy", plural: "eksterne verktøy", icon: AppWindow, tone: "teal" },
  SubHeader: { label: "Underoverskrift", plural: "underoverskrifter", icon: Heading, tone: "neutral" },
};

/** «4 sider · 1 oppgave · 1 quiz» – counts of the real items in the module. */
function itemSummary(items: StructureItem[]): string {
  const counts = new Map<string, number>();
  for (const item of items) if (item.type !== "SubHeader") counts.set(item.type, (counts.get(item.type) ?? 0) + 1);
  return [...counts.entries()]
    .map(([type, n]) => {
      const info = ITEM_TYPE[type];
      if (!info) return `${n} ${type}`;
      return `${n} ${n === 1 ? info.label.toLowerCase() : info.plural}`;
    })
    .join(" · ");
}

function Journey({ steps, label }: { steps: string[]; label: string }) {
  if (!steps.length) return <p className="ek-small ek-muted">Modulen har ikke innhold ennå.</p>;
  return (
    <ol className="ek-journey" aria-label={label}>
      <li className="ek-journey__item">
        <span className="ek-journey__step" data-tone="neutral">
          <Flag aria-hidden="true" />
          Start
        </span>
      </li>
      {steps.map((step, i) => {
        const Icon = STEP_ICON[step];
        return (
          <li key={i} className="ek-journey__item">
            <ArrowRight aria-hidden="true" className="ek-journey__arrow" />
            <span className="ek-journey__step" data-tone={STEP_TONE[step] ?? "neutral"}>
              {Icon ? <Icon aria-hidden="true" /> : null}
              {step}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function StudentJourney() {
  const { courseId } = useCurrentCourse();
  const ui = useUi();
  const structure = useQuery({
    queryKey: ["structure", courseId],
    queryFn: () => api.get<StructureResponse>(`/api/courses/${courseId}/structure`),
    enabled: Boolean(courseId),
  });
  if (!courseId) return <EmptyState title="Velg et emne">Velg et emne i toppen av siden.</EmptyState>;
  if (structure.isPending) return <Spinner label="Henter emnestrukturen …" />;
  if (structure.error) {
    return <Alert tone="danger" role="alert" title="Kunne ikke hente strukturen">{(structure.error as Error).message}</Alert>;
  }
  if (!structure.data.snapshot_at) {
    return (
      <EmptyState title="Ingen analyse ennå" headingLevel={3}
        actions={<Button variant="primary" onClick={() => ui.openAnalysis({ domains: ["structure"] })}>Kjør analyse</Button>}>
        Studentreisen bygges fra siste analyse av emnet.
      </EmptyState>
    );
  }
  return (
    <div className="ek-stack" data-gap="6">
      <p className="ek-small ek-muted">
        Slik møter studentene innholdet, modul for modul, ut fra rekkefølgen i Canvas (analyse{" "}
        {formatDateTime(structure.data.snapshot_at)}). Visningen viser rekkefølgen – den sier ikke at én
        undervisningsform er riktig.
      </p>
      {structure.data.modules.map((module, index) => (
        <Card
          key={module.id}
          eyebrow={`Modul ${index + 1}`}
          title={module.name}
          description={itemSummary(module.items) || "Ingen elementer"}
          headingLevel={3}
          actions={
            <>
              {module.published === false ? <Badge tone="warning">Upublisert</Badge> : null}
              {module.require_sequential_progress ? <Badge tone="info">Må tas i rekkefølge</Badge> : null}
              {module.requirement_type === "one" ? <Badge>Ett krav må fullføres</Badge> : null}
            </>
          }
        >
          <div className="ek-stack">
            <Journey steps={module.journey} label={`Studentreisen i ${module.name}`} />
            {module.items.length ? (
              <ol className="ek-item-list">
                {module.items.map((item) => {
                  const info = ITEM_TYPE[item.type];
                  const Icon = info?.icon ?? FileText;
                  return (
                    <li key={item.id} className="ek-item-row" style={{ paddingLeft: `${item.indent * 1.5}rem` }}>
                      <IconTile tone={info?.tone ?? "neutral"} size="sm" shape="square">
                        <Icon />
                      </IconTile>
                      <div className="ek-item-row__main">
                        {item.url ? <ExternalLink href={item.url}>{item.title}</ExternalLink> : <span>{item.title}</span>}
                        <span className="ek-item-row__meta">
                          {info?.label ?? item.type}
                          {item.due_at ? ` · frist ${formatDate(item.due_at)}` : ""}
                          {item.requirement ? ` · krav: ${item.requirement}` : ""}
                        </span>
                      </div>
                      <div className="ek-item-row__side">
                        {item.published === false ? <Badge tone="warning" dot>Upublisert</Badge> : null}
                      </div>
                    </li>
                  );
                })}
              </ol>
            ) : null}
          </div>
        </Card>
      ))}
    </div>
  );
}

export function CourseStructurePage() {
  usePageTitle("Emnestruktur");
  const ui = useUi();
  const session = useSession();
  const journeyEnabled = session.flags.student_journey !== false;
  const [tab, setTab] = useState<"suggestions" | "journey">("suggestions");
  return (
    <>
      <PageHeader
        title="Emnestruktur"
        description="Råd om moduler, rekkefølge, navngiving og plassering. Forslagene er veiledende – ingenting flyttes uten at du godkjenner det."
        actions={
          <>
            <HelpLink topic="emnestruktur" />
            <Button variant="primary" icon={<Play aria-hidden="true" />} onClick={() => ui.openAnalysis({ domains: ["structure"] })}>
              Analyser emnestruktur
            </Button>
          </>
        }
      />
      <Tabs
        label="Emnestruktur"
        selected={journeyEnabled ? tab : "suggestions"}
        onSelect={setTab}
        tabs={[
          { id: "suggestions", label: "Forslag", icon: <Lightbulb aria-hidden="true" /> },
          ...(journeyEnabled ? [{ id: "journey" as const, label: "Studentreisen", icon: <Route aria-hidden="true" /> }] : []),
        ]}
      >
        <div className="ek-mt-6">
          {tab === "journey" && journeyEnabled ? (
            <StudentJourney />
          ) : (
            <FindingsView
              domain="structure"
              emptyText="Kjør en analyse for å få forslag til emnestrukturen. Analysen leser bare fra Canvas."
            />
          )}
        </div>
      </Tabs>
    </>
  );
}

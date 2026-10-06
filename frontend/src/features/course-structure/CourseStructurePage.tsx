import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Play } from "lucide-react";
import { useState } from "react";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDate, formatDateTime } from "../../core/format";
import { useSession } from "../../core/session";
import { usePageTitle } from "../../core/usePageTitle";
import { useUi } from "../../core/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ExternalLink,
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
  Les: "info", Innlevering: "warning", Quiz: "teal", Diskusjon: "violet", Fil: "neutral",
  "Ekstern ressurs": "neutral", Verktøy: "neutral",
};
const ITEM_TYPE: Record<string, string> = {
  Page: "Side", Assignment: "Oppgave", Quiz: "Quiz", Discussion: "Diskusjon", File: "Fil",
  ExternalUrl: "Ekstern lenke", ExternalTool: "Eksternt verktøy", SubHeader: "Underoverskrift",
};

function Journey({ steps, label }: { steps: string[]; label: string }) {
  if (!steps.length) return <p className="ek-small ek-muted">Modulen har ikke innhold ennå.</p>;
  return (
    <ol className="ek-journey" aria-label={label}>
      <li className="ek-journey__step" data-tone="neutral">Start</li>
      {steps.map((step, i) => (
        <li key={i} className="ek-cluster" data-gap="2">
          <ArrowRight aria-hidden="true" size={14} className="ek-journey__arrow" />
          <span className="ek-journey__step" data-tone={STEP_TONE[step] ?? "neutral"}>{step}</span>
        </li>
      ))}
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
      {structure.data.modules.map((module) => (
        <Card
          key={module.id}
          title={module.name}
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
              <ol className="ek-list-reset ek-divider-list">
                {module.items.map((item) => (
                  <li key={item.id} className="ek-row" style={{ paddingLeft: `${item.indent * 1.25}rem` }}>
                    <div className="ek-row__main">
                      {item.url ? <ExternalLink href={item.url}>{item.title}</ExternalLink> : <span>{item.title}</span>}
                      <span className="ek-xs ek-muted">
                        {ITEM_TYPE[item.type] ?? item.type}
                        {item.due_at ? ` · frist ${formatDate(item.due_at)}` : ""}
                        {item.requirement ? ` · krav: ${item.requirement}` : ""}
                      </span>
                    </div>
                    {item.published === false ? <Badge tone="warning">Upublisert</Badge> : null}
                  </li>
                ))}
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
          <Button variant="primary" icon={<Play aria-hidden="true" />} onClick={() => ui.openAnalysis({ domains: ["structure"] })}>
            Analyser emnestruktur
          </Button>
        }
      />
      <Tabs
        label="Emnestruktur"
        selected={journeyEnabled ? tab : "suggestions"}
        onSelect={setTab}
        tabs={[
          { id: "suggestions", label: "Forslag" },
          ...(journeyEnabled ? [{ id: "journey" as const, label: "Studentreisen" }] : []),
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

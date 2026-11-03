import { useQuery } from "@tanstack/react-query";
import { BookOpenText, CircleCheck, CircleX, FlaskConical, History, ListChecks, Lock, Settings2, TriangleAlert, Undo2 } from "lucide-react";
import type { ReactNode } from "react";
import { Route, Routes } from "react-router";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDate, formatTime } from "../../core/format";
import { HelpLink } from "../../core/HelpLink";
import { useSession } from "../../core/session";
import { usePageTitle } from "../../core/usePageTitle";
import {
  ActivityList,
  Badge,
  Card,
  FeatureCard,
  IconTile,
  MoreLink,
  PageHeader,
  Spinner,
  StatusBadge,
} from "../../design-system";
import { BlueprintLocking } from "./BlueprintLocking";
import { CanvasSettings } from "./CanvasSettings";
import { ACTION, ChangeLog, type LogEntry } from "./ChangeLog";
import { ModuleRequirements } from "./ModuleRequirements";
import { CourseRag } from "./rag/CourseRag";

interface Capabilities {
  capabilities: { key: string; label: string; granted: boolean }[];
  blueprint: { is_blueprint: boolean; is_child: boolean };
}

const ACTION_ICON: Record<LogEntry["action"], ReactNode> = {
  apply: <CircleCheck />,
  dry_run: <FlaskConical />,
  conflict: <TriangleAlert />,
  failed: <CircleX />,
  undo: <Undo2 />,
};

/** The latest entries of the change log for this course. */
function RecentActions() {
  const { courseId } = useCurrentCourse();
  const log = useQuery({
    queryKey: ["changelog", courseId, "recent"],
    queryFn: () => api.get<{ items: LogEntry[]; total: number }>(`/api/changelog?course_id=${courseId}&limit=4`),
    enabled: Boolean(courseId),
  });
  return (
    <Card title="Siste handlinger" actions={<MoreLink to="endringslogg">Se alle handlinger</MoreLink>}>
      {!courseId ? (
        <p className="ek-muted">Velg et emne i toppen av siden.</p>
      ) : log.isPending ? (
        <Spinner label="Henter endringsloggen …" />
      ) : log.error ? (
        <p className="ek-muted">Kunne ikke hente endringsloggen.</p>
      ) : log.data.items.length === 0 ? (
        <p className="ek-muted">Ingen endringer ennå. Alt du gjennomfører eller prøver i Dry run, vises her.</p>
      ) : (
        <ActivityList
          label="Siste handlinger"
          items={log.data.items.map((entry) => ({
            key: String(entry.id),
            icon: ACTION_ICON[entry.action] ?? <CircleCheck />,
            tone: ACTION[entry.action]?.tone ?? "neutral",
            title: entry.object_title ?? entry.kind,
            meta: ACTION[entry.action]?.label ?? entry.action,
            date: entry.timestamp ? formatDate(entry.timestamp) : undefined,
            time: entry.timestamp ? formatTime(entry.timestamp) : undefined,
          }))}
        />
      )}
    </Card>
  );
}

function DryRunCard() {
  const session = useSession();
  return (
    <Card title="Dry run" actions={<StatusBadge tone={session.dry_run ? "warning" : "neutral"}>{session.dry_run ? "På" : "Av"}</StatusBadge>}>
      <div className="ek-cluster" data-align="start" data-gap="4" data-wrap="false">
        <IconTile tone="violet" size="lg" shape="square">
          <FlaskConical />
        </IconTile>
        <div className="ek-stack" data-gap="2">
          <p>
            Når Dry run er på, sendes ingen endringer til Canvas. Du kan likevel analysere, forhåndsvise og legge endringer
            i kø.
          </p>
          <p className="ek-small ek-muted">Bryteren «Dry run» øverst på siden gjelder alle verktøyene og hele EmneKlar.</p>
        </div>
      </div>
    </Card>
  );
}

function Overview() {
  usePageTitle("Canvas-verktøy");
  const { courseId } = useCurrentCourse();
  const session = useSession();
  const caps = useQuery({
    queryKey: ["capabilities", courseId],
    queryFn: () => api.get<Capabilities>(`/api/courses/${courseId}/capabilities`),
    enabled: Boolean(courseId),
    staleTime: 60_000,
  });
  const granted = (key: string) => caps.data?.capabilities.find((c) => c.key === key)?.granted;
  const missing = (key: string) =>
    caps.data && granted(key) === false ? <Badge tone="warning">Du mangler tilgang i Canvas</Badge> : null;
  const blueprint = caps.data?.blueprint;
  return (
    <>
      <PageHeader title="Canvas-verktøy" description="Administrative verktøy for trygg forbedring i Canvas. Alt forhåndsvises og går via endringskøen."
        actions={<HelpLink topic="canvas-verktoy" />} />
      <div className="ek-stack" data-gap="6">
        <div className="ek-split" data-align="stretch">
          <RecentActions />
          <DryRunCard />
        </div>
        <div className="ek-grid" data-cols="2" data-gap="6">
          <FeatureCard to="modulkrav" icon={<ListChecks />} tone="success" title="Automatiske modulkrav" actionLabel="Åpne"
            description="Foreslå fullføringskrav ut fra elementtype, og velg om modulene skal fullføres i rekkefølge.">
            {missing("modules")}
          </FeatureCard>
          <FeatureCard to="blueprint" icon={<Lock />} tone="info" title="Blueprint-låsing" actionLabel="Åpne"
            description="Lås eller lås opp innhold i et Blueprint-emne, samlet og med forhåndsvisning.">
            {blueprint ? (
              blueprint.is_blueprint ? <Badge tone="success">Blueprint-emne</Badge>
                : <Badge>Ikke tilgjengelig – emnet er ikke et Blueprint-emne</Badge>
            ) : null}
          </FeatureCard>
          <FeatureCard to="innstillinger" icon={<Settings2 />} tone="violet" title="Canvas-innstillinger" actionLabel="Åpne"
            description="Gjennomgang av innstillinger for emnet, sider, oppgaver og quizer – sortert etter hva som bør gjøres.">
            {missing("settings")}
          </FeatureCard>
          <FeatureCard to="endringslogg" icon={<History />} tone="orange" title="Backup og endringslogg" actionLabel="Se logg"
            description="Se alt EmneKlar har endret, last ned sikkerhetskopier og angre endringer der det er trygt." />
          {session.flags.course_rag !== false ? (
            <FeatureCard to="emne-rag" icon={<BookOpenText />} tone="teal" title="Emne-RAG" actionLabel="Åpne"
              description="Lag en lokal kunnskapsbase av emnet – tekst, dokumenter, bilder og video – og still spørsmål med kildehenvisninger.">
              <Badge tone="info">Bare lesing fra Canvas</Badge>
            </FeatureCard>
          ) : null}
        </div>
      </div>
    </>
  );
}

export function CanvasToolsPage() {
  return (
    <Routes>
      <Route index element={<Overview />} />
      <Route path="modulkrav" element={<Titled title="Automatiske modulkrav"><ModuleRequirements /></Titled>} />
      <Route path="blueprint" element={<Titled title="Blueprint-låsing"><BlueprintLocking /></Titled>} />
      <Route path="innstillinger" element={<Titled title="Canvas-innstillinger"><CanvasSettings /></Titled>} />
      <Route path="endringslogg" element={<Titled title="Backup og endringslogg"><ChangeLog /></Titled>} />
      <Route path="emne-rag" element={<Titled title="Emne-RAG"><CourseRag /></Titled>} />
    </Routes>
  );
}

function Titled({ title, children }: { title: string; children: ReactNode }) {
  usePageTitle(title);
  return <>{children}</>;
}

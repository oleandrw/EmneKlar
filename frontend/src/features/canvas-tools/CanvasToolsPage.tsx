import { useQuery } from "@tanstack/react-query";
import { BookOpenText, CircleCheck, CircleX, History, ImagePlus, ListChecks, Lock, Settings2, TriangleAlert, Undo2 } from "lucide-react";
import type { ReactNode } from "react";
import { Route, Routes } from "react-router";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { formatDate, formatTime } from "../../core/format";
import { useSession } from "../../core/session";
import { usePageTitle } from "../../core/usePageTitle";
import { ActivityList, Card, FeatureCard, MoreLink, PageHeader, Spinner } from "../../design-system";
import { BlueprintLocking } from "./BlueprintLocking";
import { CanvasSettings } from "./CanvasSettings";
import { ACTION, historyLine } from "../changes/history";
import { CHANGE_LOG_TITLE, ChangeLog, type LogEntry } from "./ChangeLog";
import { IllustrationAssistant } from "./illustrations/IllustrationAssistant";
import { ModuleRequirements } from "./ModuleRequirements";
import { CourseRag } from "./rag/CourseRag";

interface Capabilities {
  capabilities: { key: string; label: string; granted: boolean }[];
  blueprint: { is_blueprint: boolean; is_child: boolean };
}

const ACTION_ICON: Record<LogEntry["action"], ReactNode> = {
  apply: <CircleCheck />,
  dry_run: <History />,
  conflict: <TriangleAlert />,
  failed: <CircleX />,
  undo: <Undo2 />,
};

/** The latest entries of the change log for this course: the content, what was changed, the status and when. */
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
        <p className="ek-muted">Ingen endringer ennå. Alt du publiserer til Canvas, vises her.</p>
      ) : (
        <ActivityList
          label="Siste handlinger"
          items={log.data.items.map((entry) => ({
            key: String(entry.id),
            icon: ACTION_ICON[entry.action] ?? <CircleCheck />,
            tone: ACTION[entry.action]?.tone ?? "neutral",
            title: entry.object_title ?? entry.summary ?? entry.object_id ?? "Endring",
            meta: historyLine(entry),
            date: entry.timestamp ? formatDate(entry.timestamp) : undefined,
            time: entry.timestamp ? formatTime(entry.timestamp) : undefined,
          }))}
        />
      )}
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
  const missing = (key: string, what: string) =>
    caps.data && granted(key) === false ? `Du mangler tilgang i Canvas til å endre ${what} i dette emnet.` : undefined;
  const blueprint = caps.data?.blueprint;
  return (
    <>
      <PageHeader title="Canvas-verktøy" description="Du forhåndsviser og godkjenner endringer før de publiseres til Canvas." />
      <div className="ek-stack" data-gap="6">
        {/* One calm palette with meaning: blue for tools that work on the course in Canvas, violet for KI tools (as the
            «KI-forslag» marks), neutral for the record of changes. Orange and red are for something that needs
            attention – not decoration. */}
        <div className="ek-grid" data-cols="2">
          <FeatureCard to="modulkrav" icon={<ListChecks />} tone="info" title="Automatiske modulkrav"
            actionLabel="Sett modulkrav" notice={missing("modules", "moduler")}
            description="Foreslå fullføringskrav ut fra elementtype, og velg om modulene skal fullføres i rekkefølge." />
          <FeatureCard to="blueprint" icon={<Lock />} tone="info" title="Blueprint-låsing" actionLabel="Administrer låsing"
            description="Lås eller lås opp innhold i et Blueprint-emne, samlet og med forhåndsvisning."
            notice={blueprint && !blueprint.is_blueprint ? "Ikke tilgjengelig her – emnet er ikke et Blueprint-emne." : undefined}
            noticeTone="info" />
          <FeatureCard to="innstillinger" icon={<Settings2 />} tone="info" title="Canvas-innstillinger"
            actionLabel="Se innstillinger" notice={missing("settings", "innstillinger")}
            description="Gjennomgang av innstillinger for emnet, sider, oppgaver og quizer – sortert etter hva som bør gjøres." />
          <FeatureCard to="endringslogg" icon={<History />} tone="neutral" title={CHANGE_LOG_TITLE}
            actionLabel="Se endringer og sikkerhetskopier"
            description="Se alt EmneKlar har endret, last ned sikkerhetskopier og angre endringer der det er trygt." />
          {session.flags.course_rag !== false ? (
            <FeatureCard to="emne-rag" icon={<BookOpenText />} tone="violet" title="Emnets kunnskapsbase"
              actionLabel="Åpne kunnskapsbasen"
              description="Samle tekst, dokumenter, bilder og video fra emnet, og still spørsmål med kildehenvisninger. Innholdet lagres lokalt på denne maskinen, og ingenting endres i Canvas." />
          ) : null}
          {session.flags.illustration_assistant !== false ? (
            <FeatureCard to="bildeassistent" icon={<ImagePlus />} tone="violet" title="KI-bildeassistent"
              actionLabel="Lag illustrasjoner"
              description="Faglig presise illustrasjoner for hele emnet, moduler eller én side – i én gjennomgående stil, med alt-tekst og bildetekst. Du godkjenner bildene før de settes inn i Canvas, med mindre du velger «Automatisk innsetting»." />
          ) : null}
        </div>
        <RecentActions />
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
      <Route path="endringslogg" element={<Titled title={CHANGE_LOG_TITLE}><ChangeLog /></Titled>} />
      <Route path="emne-rag" element={<Titled title="Emnets kunnskapsbase"><CourseRag /></Titled>} />
      <Route path="bildeassistent" element={<Titled title="KI-bildeassistent"><IllustrationAssistant /></Titled>} />
    </Routes>
  );
}

function Titled({ title, children }: { title: string; children: ReactNode }) {
  usePageTitle(title);
  return <>{children}</>;
}

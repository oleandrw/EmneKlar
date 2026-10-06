import { useQuery } from "@tanstack/react-query";
import { History, ListChecks, Lock, Settings2 } from "lucide-react";
import type { ReactNode } from "react";
import { Link, Route, Routes } from "react-router";

import { api } from "../../core/api/client";
import { useCurrentCourse } from "../../core/course";
import { HelpLink } from "../../core/HelpLink";
import { usePageTitle } from "../../core/usePageTitle";
import { Badge, IconCircle, PageHeader } from "../../design-system";
import { BlueprintLocking } from "./BlueprintLocking";
import { CanvasSettings } from "./CanvasSettings";
import { ChangeLog } from "./ChangeLog";
import { ModuleRequirements } from "./ModuleRequirements";

interface Capabilities {
  capabilities: { key: string; label: string; granted: boolean }[];
  blueprint: { is_blueprint: boolean; is_child: boolean };
}

function ToolCard({ to, icon, title, children, status }: { to: string; icon: ReactNode; title: string; children: ReactNode; status?: ReactNode }) {
  return (
    <Link to={to} className="ek-card ek-card--link">
      <div className="ek-stack" data-gap="2">
        <IconCircle tone="info">{icon}</IconCircle>
        <h2 className="ek-card__title">{title}</h2>
        <p className="ek-small ek-muted">{children}</p>
        {status}
      </div>
    </Link>
  );
}

function Overview() {
  usePageTitle("Canvas-verktøy");
  const { courseId } = useCurrentCourse();
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
      <PageHeader title="Canvas-verktøy" description="Utvalgte administrative verktøy for emnet. Alt forhåndsvises og går via endringskøen."
        actions={<HelpLink topic="canvas-verktoy" />} />
      <div className="ek-grid" data-cols="2">
        <ToolCard to="modulkrav" icon={<ListChecks />} title="Automatiske modulkrav" status={missing("modules")}>
          Foreslå fullføringskrav ut fra elementtype, og velg om modulene skal fullføres i rekkefølge.
        </ToolCard>
        <ToolCard to="blueprint" icon={<Lock />} title="Blueprint-låsing"
          status={blueprint ? (
            blueprint.is_blueprint ? <Badge tone="success">Blueprint-emne</Badge>
              : <Badge>Ikke tilgjengelig – emnet er ikke et Blueprint-emne</Badge>
          ) : null}>
          Lås eller lås opp innhold i et Blueprint-emne, samlet og med forhåndsvisning.
        </ToolCard>
        <ToolCard to="innstillinger" icon={<Settings2 />} title="Canvas-innstillinger" status={missing("settings")}>
          Gjennomgang av innstillinger for emnet, sider, oppgaver og quizer – sortert etter hva som bør gjøres.
        </ToolCard>
        <ToolCard to="endringslogg" icon={<History />} title="Backup og endringslogg">
          Se alt EmneKlar har endret, last ned sikkerhetskopier og angre endringer der det er trygt.
        </ToolCard>
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
    </Routes>
  );
}

function Titled({ title, children }: { title: string; children: ReactNode }) {
  usePageTitle(title);
  return <>{children}</>;
}

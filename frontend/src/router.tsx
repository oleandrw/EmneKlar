import { Navigate, Route, Routes, useLocation } from "react-router";

import { AppShell } from "./core/layout/AppShell";
import { usePageTitle } from "./core/usePageTitle";
import { useSession } from "./core/session";
import { ButtonLink, EmptyState, PageHeader } from "./design-system";
import { AccessibilityPage } from "./features/accessibility/AccessibilityPage";
import { CanvasToolsPage } from "./features/canvas-tools/CanvasToolsPage";
import { ContentQualityPage } from "./features/content-quality/ContentQualityPage";
import { CourseStructurePage } from "./features/course-structure/CourseStructurePage";
import { HelpPage } from "./features/help/HelpPage";
import { HomepageBuilderPage } from "./features/homepage/HomepageBuilderPage";
import { OverviewPage } from "./features/overview/OverviewPage";
import { QuizAssistantPage } from "./features/quiz-assistant/QuizAssistantPage";
import { ReportsPage } from "./features/reports/ReportsPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { SetupWizard } from "./features/setup/SetupWizard";

const START_PATHS: Record<string, string> = {
  oversikt: "/oversikt",
  "universell-utforming": "/universell-utforming",
  innholdskvalitet: "/innholdskvalitet",
  emnestruktur: "/emnestruktur",
  quizassistent: "/quizassistent",
  emneforside: "/emneforside",
  "canvas-verktoy": "/canvas-verktoy",
  rapporter: "/rapporter",
};

function NotFound() {
  usePageTitle("Fant ikke siden");
  return (
    <>
      <PageHeader title="Fant ikke siden" />
      <EmptyState
        title="Denne siden finnes ikke"
        actions={
          <ButtonLink to="/oversikt" variant="primary">
            Gå til oversikten
          </ButtonLink>
        }
      >
        Adressen kan være skrevet feil, eller siden kan være flyttet.
      </EmptyState>
    </>
  );
}

export function AppRoutes() {
  const session = useSession();
  const location = useLocation();
  if (!session.setup_completed && !location.pathname.startsWith("/oppsett") && !location.pathname.startsWith("/hjelp")) {
    return <Navigate to="/oppsett" replace />;
  }
  return (
    <Routes>
      <Route path="/oppsett" element={<SetupWizard />} />
      <Route
        path="*"
        element={
          <AppShell>
            <Routes>
              <Route index element={<Navigate to={START_PATHS[session.general.start_page] ?? "/oversikt"} replace />} />
              <Route path="oversikt" element={<OverviewPage />} />
              <Route path="universell-utforming" element={<AccessibilityPage />} />
              <Route path="innholdskvalitet" element={<ContentQualityPage />} />
              <Route path="emnestruktur" element={<CourseStructurePage />} />
              <Route path="quizassistent/*" element={<QuizAssistantPage />} />
              <Route path="emneforside" element={<HomepageBuilderPage />} />
              <Route path="canvas-verktoy/*" element={<CanvasToolsPage />} />
              <Route path="rapporter" element={<ReportsPage />} />
              <Route path="innstillinger/:section?" element={<SettingsPage />} />
              <Route path="hjelp/:topic?" element={<HelpPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </AppShell>
        }
      />
    </Routes>
  );
}

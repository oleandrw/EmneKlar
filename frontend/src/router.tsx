import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";

import { AppShell } from "./core/layout/AppShell";
import { usePageTitle } from "./core/usePageTitle";
import { useSession } from "./core/session";
import { ButtonLink, EmptyState, PageHeader, Spinner } from "./design-system";
import { OverviewPage } from "./features/overview/OverviewPage";
import { SetupWizard } from "./features/setup/SetupWizard";

// Feature pages are loaded on demand, so the first screen appears quickly.
const AccessibilityPage = lazy(() => import("./features/accessibility/AccessibilityPage").then((m) => ({ default: m.AccessibilityPage })));
const CanvasToolsPage = lazy(() => import("./features/canvas-tools/CanvasToolsPage").then((m) => ({ default: m.CanvasToolsPage })));
const CourseDesignPage = lazy(() => import("./features/course-design/CourseDesign").then((m) => ({ default: m.CourseDesignPage })));
const ContentQualityPage = lazy(() => import("./features/content-quality/ContentQualityPage").then((m) => ({ default: m.ContentQualityPage })));
const CourseStructurePage = lazy(() => import("./features/course-structure/CourseStructurePage").then((m) => ({ default: m.CourseStructurePage })));
const HelpPage = lazy(() => import("./features/help/HelpPage").then((m) => ({ default: m.HelpPage })));
const QuizAssistantPage = lazy(() => import("./features/quiz-assistant/QuizAssistantPage").then((m) => ({ default: m.QuizAssistantPage })));
const ReportsPage = lazy(() => import("./features/reports/ReportsPage").then((m) => ({ default: m.ReportsPage })));
const SettingsPage = lazy(() => import("./features/settings/SettingsPage").then((m) => ({ default: m.SettingsPage })));

const START_PATHS: Record<string, string> = {
  oversikt: "/oversikt",
  "universell-utforming": "/universell-utforming",
  innholdskvalitet: "/innholdskvalitet",
  emnestruktur: "/emnestruktur",
  quizassistent: "/quizassistent",
  emnedesign: "/emnedesign",
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
            <Suspense fallback={<Spinner label="Laster siden …" />}>
            <Routes>
              <Route index element={<Navigate to={START_PATHS[session.general.start_page] ?? "/oversikt"} replace />} />
              <Route path="oversikt" element={<OverviewPage />} />
              <Route path="universell-utforming" element={<AccessibilityPage />} />
              <Route path="innholdskvalitet" element={<ContentQualityPage />} />
              <Route path="emnestruktur" element={<CourseStructurePage />} />
              <Route path="quizassistent/*" element={<QuizAssistantPage />} />
              <Route path="emnedesign" element={<CourseDesignPage />} />
              <Route path="canvas-verktoy/*" element={<CanvasToolsPage />} />
              <Route path="rapporter" element={<ReportsPage />} />
              <Route path="innstillinger/:section?" element={<SettingsPage />} />
              <Route path="hjelp/:topic?" element={<HelpPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
            </Suspense>
          </AppShell>
        }
      />
    </Routes>
  );
}

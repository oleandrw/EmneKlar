import { FileText, Layers, Plus, Sparkles, TriangleAlert } from "lucide-react";
import { Route, Routes, useLocation } from "react-router";

import { useCurrentCourse } from "../../core/course";
import { useSession } from "../../core/session";
import { HelpLink } from "../../core/HelpLink";
import { usePageTitle } from "../../core/usePageTitle";
import { Alert, MetricCard, NavTabs, PageHeader } from "../../design-system";
import { useBank, useQuizzes } from "./api";
import { QuizList, QuizReview } from "./ExistingQuizzes";
import { QuestionBank } from "./QuestionBank";
import { QuizBuilder } from "./QuizBuilder";

/** Key figures for the course's quizzes and question bank (only shown when the data is loaded). */
function QuizSummary() {
  const { courseId } = useCurrentCourse();
  const quizzes = useQuizzes(courseId);
  const bank = useBank(courseId, { status: "", module: "", q: "" });
  if (!courseId || !quizzes.data) return null;
  const list = quizzes.data.quizzes;
  const published = list.filter((q) => q.published).length;
  const questions = list.reduce((sum, q) => sum + (q.question_count ?? 0), 0);
  const findings = list.reduce((sum, q) => sum + (q.open_findings ?? 0), 0);
  return (
    <div className="ek-grid" data-cols="4" data-gap="5">
      <MetricCard icon={<FileText />} tone="info" shape="square" value={list.length} label={list.length === 1 ? "quiz" : "quizer"}
        description={`${published} publisert · ${list.length - published} upublisert`} />
      <MetricCard icon={<Layers />} tone="success" shape="square" value={questions} label="spørsmål" description="Totalt i alle quizer" />
      <MetricCard icon={<TriangleAlert />} tone="warning" shape="square" value={findings} valueTone={findings ? "warning" : "neutral"}
        label="åpne funn" description="Mulige feil eller uklare spørsmål" />
      <MetricCard icon={<Sparkles />} tone="violet" shape="square" value={bank.data?.counts.draft ?? "–"}
        label="til vurdering" description="Ikke godkjent i KI-spørsmålsbanken" />
    </div>
  );
}

export function QuizAssistantPage() {
  usePageTitle("Quizassistent");
  const session = useSession();
  const { pathname } = useLocation();
  const onExisting = pathname.replace(/\/$/, "") === "/quizassistent" || pathname.startsWith("/quizassistent/quiz/");
  if (session.flags.quiz_assistant === false) {
    return (
      <>
        <PageHeader title="Quizassistent" />
        <Alert tone="info" title="Quizassistenten er slått av">
          Funksjonen kan slås på under Innstillinger → Avanserte innstillinger.
        </Alert>
      </>
    );
  }
  return (
    <>
      <PageHeader
        title="Quizassistent"
        description="Kvalitetssjekk av klassiske quizer, KI-spørsmålsbank og bygging av nye quizer. Fasit endres aldri automatisk."
        actions={<HelpLink topic="quizassistent" />}
      />
      <div className="ek-stack" data-gap="6">
        <QuizSummary />
        <NavTabs
          label="Quizassistent"
          items={[
            { to: "/quizassistent", label: "Eksisterende quizer", current: onExisting, icon: <FileText aria-hidden="true" /> },
            { to: "/quizassistent/sporsmalsbank", label: "KI-spørsmålsbank", icon: <Sparkles aria-hidden="true" /> },
            { to: "/quizassistent/ny-quiz", label: "Lag ny quiz", icon: <Plus aria-hidden="true" /> },
          ]}
        />
        <Routes>
          <Route index element={<QuizList />} />
          <Route path="quiz/:quizId" element={<QuizReview />} />
          <Route path="sporsmalsbank" element={<QuestionBank />} />
          <Route path="ny-quiz" element={<QuizBuilder />} />
        </Routes>
      </div>
    </>
  );
}

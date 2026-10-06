import { Route, Routes, useLocation } from "react-router";

import { useSession } from "../../core/session";
import { HelpLink } from "../../core/HelpLink";
import { usePageTitle } from "../../core/usePageTitle";
import { Alert, NavTabs, PageHeader } from "../../design-system";
import { QuizList, QuizReview } from "./ExistingQuizzes";
import { QuestionBank } from "./QuestionBank";
import { QuizBuilder } from "./QuizBuilder";

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
        <NavTabs
          label="Quizassistent"
          items={[
            { to: "/quizassistent", label: "Eksisterende quizer", current: onExisting },
            { to: "/quizassistent/sporsmalsbank", label: "KI-spørsmålsbank" },
            { to: "/quizassistent/ny-quiz", label: "Lag ny quiz" },
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

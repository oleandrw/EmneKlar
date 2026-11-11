import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../core/ui";
import { ToastProvider } from "../../design-system";
import { QuizReview } from "./ExistingQuizzes";

vi.mock("../../core/session", () => ({
  useSession: () => ({ canvas: { token_configured: true }, ai: { providers_enabled: [], external_allowed: false,
    confirm_before_send: true }, flags: {}, general: { page_size: 25 } }),
}));
vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

const detail = {
  quiz: { id: "501", title: "Quiz 1: Bildeformater", html_url: null, groups: [],
    settings: { quiz_type: "assignment", allowed_attempts: 1, shuffle_answers: false, time_limit: null, published: true } },
  questions: [], findings: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("quiz detail", () => {
  it("has no second primary action – checking only this quiz is a quiet action that starts the same check", async () => {
    const calls: { url: string; method?: string; body?: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method, body: init?.body ? String(init.body) : undefined });
      if (url.endsWith("/review")) {
        return new Response(JSON.stringify({ error: { code: "conflict", message: "En kontroll pågår allerede." } }),
          { status: 409 });
      }
      return new Response(JSON.stringify(detail), { status: 200 });
    }));
    const user = userEvent.setup();
    const { container } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ToastProvider><UiProvider>
          <MemoryRouter initialEntries={["/quizassistent/501"]}>
            <Routes><Route path="/quizassistent/:quizId" element={<QuizReview />} /></Routes>
          </MemoryRouter>
        </UiProvider></ToastProvider>
      </QueryClientProvider>,
    );
    const check = await screen.findByRole("button", { name: "Kontroller bare denne quizen" });
    expect(check).not.toHaveClass("ek-btn--primary");
    expect(container.querySelector(".ek-btn--primary"), "the top bar has the primary analysis action").toBeNull();
    expect(screen.getByText(/«Analyser quizkvalitet» øverst til høyre kontrollerer alle quizene i emnet/)).toBeInTheDocument();
    await user.click(check);
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/quizzes/501/review"))).toMatchObject({
      method: "POST", body: JSON.stringify({ use_ai: false, confirmed: false }) }));
  });
});

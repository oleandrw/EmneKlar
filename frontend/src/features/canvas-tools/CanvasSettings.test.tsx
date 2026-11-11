import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UiProvider } from "../../core/ui";
import { ToastProvider } from "../../design-system";
import { CanvasSettings } from "./CanvasSettings";

vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

const wrap = (children: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider><UiProvider><MemoryRouter>{children}</MemoryRouter></UiProvider></ToastProvider>
  </QueryClientProvider>
);

const HINT = "Gir studentene mulighet til å starte egne diskusjoner.";
const analysis = {
  items: [], counts: { technical: 0, security_accessibility: 0, recommendation: 0, preference: 1 },
  category_labels: { technical: "Tekniske feil", security_accessibility: "Sikkerhet og tilgjengelighet",
    recommendation: "Anbefalinger", preference: "Valg" },
  preferences: [{ key: "allow_student_discussion_topics", label: "Studenter kan opprette diskusjoner", description: HINT, value: true }],
  course: { default_view: "modules", default_view_label: "Moduler", has_front_page: true },
  checked: { pages: 1, assignments: 0, quizzes: 0 }, limitations: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("Canvas-innstillinger → Preferanser", () => {
  it("puts the help text on its own line under the switch and uses it as the switch's description", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(analysis), { status: 200 })));
    render(wrap(<CanvasSettings />));
    const toggle = await screen.findByRole("switch", { name: /Studenter kan opprette diskusjoner/ });
    expect(toggle).toHaveAccessibleDescription(HINT);
    // «På» belongs to the switch; the help text is a paragraph of its own after it – never «PåGir studentene …».
    expect(toggle).toHaveTextContent(/På$/);
    expect(toggle).not.toHaveTextContent(HINT);
    const hint = screen.getByText(HINT);
    expect(hint.tagName).toBe("P");
    expect(hint).toHaveClass("ek-mt-2");
    expect(hint.previousElementSibling).toBe(toggle);
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../design-system";
import { ReportsPage } from "./ReportsPage";

vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

const wrap = (children: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider><MemoryRouter>{children}</MemoryRouter></ToastProvider>
  </QueryClientProvider>
);

const card = (total: number, by_classification: Record<string, number>) =>
  ({ total, last_run: "2026-11-06T13:20:00+00:00", by_classification });

function serve() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url.includes("/reports/types")
      ? { types: [{ value: "full", label: "Hele emnet", analysed: true }], formats: [{ value: "html", label: "HTML" }] }
      : url.includes("/overview")
        ? { cards: {
          accessibility: card(958, { violation: 152, likely_violation: 806 }),
          content_quality: card(20, { violation: 4, should_review: 6, improvement: 4, manual_check: 6 }),
          structure: card(5, { should_review: 2, improvement: 3 }),
          quiz: card(3, { violation: 1, likely_violation: 2 }),
        } }
        : { items: [], jobs: [] };
    return new Response(JSON.stringify(body), { status: 200 });
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("Rapporter", () => {
  it("shows confirmed problems as the main figure, not every open finding in red", async () => {
    serve();
    render(wrap(<ReportsPage />));
    const label = await screen.findByText("bekreftede avvik og feil");
    const metric = label.closest(".ek-metric-card")!;
    expect(metric.querySelector(".ek-metric-card__value")).toHaveTextContent("157");
    expect(metric).toHaveAttribute("data-value-tone", "critical");
    expect(metric.querySelector(".ek-metric-card__secondary")).toHaveTextContent("808 sannsynlige avvik og feil");
    // Every open finding, suggestions and manual checks included, is plain text – not a red headline.
    expect(metric.querySelector(".ek-metric-card__description")).toHaveTextContent(/986\s*åpne funn i alt/);
    expect(screen.queryByText("åpne funn")).toBeNull();
  });
});

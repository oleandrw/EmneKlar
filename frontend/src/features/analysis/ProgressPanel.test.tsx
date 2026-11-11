import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Job } from "../../core/api/types";
import { ANALYSIS_WORDING, type JobWording, ProgressPanel } from "./ProgressPanel";

const runningJob: Job = {
  id: "job-1",
  kind: "analysis",
  course_id: "101",
  title: "Analyse av hele emnet",
  status: "running",
  supports_pause: true,
  error: null,
  result: {},
  created_at: "2026-11-06T12:00:00Z",
  started_at: "2026-11-06T12:00:01Z",
  finished_at: null,
  progress: {
    phase: "analyse",
    phase_label: "Analyserer innhold",
    phase_index: 2,
    phase_count: 3,
    determinate: true,
    percent: 40,
    done: 4,
    total: 10,
    types: {
      list: { label: "Innholdslister", total: 5, done: 5, failed: 0 },
      page: { label: "Sider", total: 6, done: 3, failed: 0 },
      file: { label: "Filer", total: 4, done: 1, failed: 1 },
    },
    current_item: "Side: Velkommen til emnet",
    current_operation: "Lenkesjekk",
    findings: { accessibility: 3, "content_quality:links": 2 },
    eta: { state: "estimate", seconds: 90 },
    in_flight: 2,
    messages: [],
  },
};

function renderPanel(wording?: JobWording) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ProgressPanel job={runningJob} wording={wording} />
    </QueryClientProvider>,
  );
}

describe("ProgressPanel", () => {
  it("shows only progress per content type for the course analysis", () => {
    renderPanel();
    expect(screen.getByText("40 % fullført")).toBeInTheDocument();
    expect(screen.getByText("Estimert tid igjen")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Fremdrift per innholdstype" });
    expect(table).toHaveTextContent("Sider");
    expect(table).toHaveTextContent("3/6");
    expect(table).toHaveTextContent("(1 feilet)");
    expect(table).not.toHaveTextContent("Innholdslister");
    expect(screen.queryByText("Nå analyseres")).not.toBeInTheDocument();
    expect(screen.queryByText("Side: Velkommen til emnet")).not.toBeInTheDocument();
    expect(screen.queryByText(/Aktiv kontroll/)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Funn så langt" })).not.toBeInTheDocument();
  });

  it("still shows the current item and findings for jobs that ask for them", () => {
    renderPanel({ ...ANALYSIS_WORDING, noun: "kontrollen", current: "Nå kontrolleres", hideCurrent: false, hideFindings: false });
    expect(screen.getByText("Nå kontrolleres")).toBeInTheDocument();
    expect(screen.getByText("Side: Velkommen til emnet")).toBeInTheDocument();
    expect(screen.getByText("Aktiv kontroll: Lenkesjekk")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Funn så langt" })).toBeInTheDocument();
  });
});

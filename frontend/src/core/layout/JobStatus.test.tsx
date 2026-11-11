import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../design-system";
import { AnalysisDialog } from "../../features/analysis/AnalysisDialog";
import { HeaderAnalysisButton, ResultsFreshness } from "../../features/analysis/AnalysisStatus";
import type { Job, JobProgress } from "../api/types";
import { JobsProvider } from "../jobs";
import { UiProvider, useUi } from "../ui";
import { JobStatus } from "./JobStatus";

// One stable session object (a new one on every render would make effects that depend on it run forever).
const session = vi.hoisted(() => ({
  canvas: { token_configured: true },
  current_course_id: "101",
  notifications: { notify_job_complete: false, browser_notifications: false },
  analysis: { default_domains: ["accessibility", "content_quality", "structure"] },
  flags: { quiz_assistant: true } as Record<string, boolean>,
}));
vi.mock("../session", () => ({ useSession: () => session }));

const progress = (over: Partial<JobProgress> = {}): JobProgress => ({
  phase: "analyze", phase_label: "Analyserer innholdet", phase_index: 2, phase_count: 2, determinate: true,
  percent: null, done: 0, total: 0, types: {}, current_item: null, current_operation: null, findings: {},
  eta: { state: "calculating" }, in_flight: 0, messages: [], version: 1, ...over,
});
const LINKS = (done: number) => ({ list: { label: "Innholdslister", total: 9, done: 9, failed: 0 },
  link: { label: "Lenker", total: 380, done, failed: 0 } });
const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const job = (over: Partial<Job> = {}): Job => ({
  id: "a", kind: "analysis", course_id: "101", title: "Analyse av hele emnet", status: "running",
  params: { course_id: "101", domains: ["content_quality"], scope: "course", module_ids: [], items: [] },
  supports_pause: true, error: null, result: {}, created_at: ago(0.1), started_at: ago(0.1), finished_at: null,
  progress: progress({ types: LINKS(124) }), ...over,
});

interface Server { jobs: Job[]; history: Job[]; fail: boolean; posted: unknown[]; methods: string[] }
let server: Server;

beforeEach(() => {
  session.current_course_id = "101";
  server = { jobs: [], history: [], fail: false, posted: [], methods: [] };
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    server.methods.push(`${init?.method ?? "GET"} ${url}`);
    const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
    if (server.fail && url.startsWith("/api/jobs")) return reply({ error: { code: "network", message: "Ingen kontakt" } }, 503);
    if (url.startsWith("/api/jobs/history")) {
      const wanted = new URL(url, "http://x").searchParams.get("status")?.split(",");
      return reply({ jobs: server.history.filter((j) => !wanted || wanted.includes(j.status)) });
    }
    if (url.startsWith("/api/jobs?")) return reply({ jobs: server.jobs });
    if (url.startsWith("/api/jobs/")) {
      const found = server.jobs.find((j) => url === `/api/jobs/${j.id}`);
      return found ? reply(found) : reply({ error: { code: "job_not_found", message: "Fant ikke jobben" } }, 404);
    }
    if (url.startsWith("/api/courses")) {
      return reply({ courses: [
        { id: "101", name: "Digital kompetanse", course_code: "LA101", term_name: null, workflow_state: "available", is_blueprint: false, default_view: null, roles: [] },
        { id: "202", name: "Matematikk", course_code: "MAT202", term_name: null, workflow_state: "available", is_blueprint: false, default_view: null, roles: [] },
      ] });
    }
    if (url === "/api/analysis" && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      server.posted.push(body);
      const created = job({ id: `new-${server.posted.length}`, params: body, created_at: new Date().toISOString(),
        progress: progress({ phase: "discover", phase_label: "Henter innhold fra Canvas", phase_index: 1, determinate: false }) });
      server.jobs = [created, ...server.jobs];
      return reply(created);
    }
    return reply({});
  }));
});
afterEach(() => vi.unstubAllGlobals());

/** The analysis dialog as the app shell has it. */
function ShellDialog() {
  const ui = useUi();
  return <AnalysisDialog open={ui.analysisOpen} onClose={ui.closeAnalysis} />;
}

function renderHeader({ path = "/innholdskvalitet", resultsAt = "2026-11-06T14:42:00Z" }: { path?: string; resultsAt?: string | null } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider>
          <UiProvider>
            <JobsProvider>
              <header className="ek-header__group">
                <JobStatus />
                <HeaderAnalysisButton />
              </header>
              <main>
                <nav aria-label="Sider">
                  <Link to="/oversikt">Til Oversikt</Link> <Link to="/universell-utforming">Til UU</Link>{" "}
                  <Link to="/emnedesign">Til Emnedesign</Link> <Link to="/quizassistent">Til Quiz</Link>{" "}
                  <Link to="/innholdskvalitet">Til Innholdskvalitet</Link>
                </nav>
                <button type="button">Eksporter rapport</button>
                <ResultsFreshness domain="content_quality" resultsAt={resultsAt} />
              </main>
              <ShellDialog />
            </JobsProvider>
          </UiProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const WAIT = { timeout: 4000 };
const statusControl = () => document.querySelector<HTMLButtonElement>(".ek-jobs-button")!;
const panel = () => screen.queryByRole("region", { name: "Analysestatus" });
const analysisButtons = () => screen.queryAllByRole("button", { name: /^Analys(er|e pågår|e:)/ });
const analysisNames = () => analysisButtons().map((b) => b.getAttribute("aria-label") ?? b.textContent);
const spinners = () => document.querySelectorAll(".ek-spinner");

describe("one analysis button that follows the page", () => {
  it("has the page's text and action, and no button where the page has no analysis of its own", async () => {
    renderHeader({ path: "/innholdskvalitet" });
    const user = userEvent.setup();
    await waitFor(() => expect(analysisNames()).toEqual(["Analyser innholdskvalitet"]));
    await user.click(screen.getByRole("link", { name: "Til Oversikt" }));
    expect(analysisNames()).toEqual(["Analyser hele emnet"]);
    await user.click(screen.getByRole("link", { name: "Til UU" }));
    expect(analysisNames()).toEqual(["Analyser universell utforming"]);
    await user.click(screen.getByRole("link", { name: "Til Quiz" }));
    expect(analysisNames()).toEqual(["Analyser quizkvalitet"]);
    await user.click(screen.getByRole("link", { name: "Til Emnedesign" }));
    expect(analysisButtons(), "no made-up analysis").toEqual([]);
    // At rest: a discreet icon with «Analysestatus» as name and tooltip – no text, no animation.
    expect(statusControl()).toHaveAccessibleName("Analysestatus");
    expect(statusControl()).toHaveAttribute("title", "Analysestatus");
    expect(statusControl().textContent).toBe("");
    expect(spinners()).toHaveLength(0);
  });

  it("from an area page it analyses only that area – no full analysis – and keeps focus on the button", async () => {
    renderHeader({ path: "/innholdskvalitet" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Analyser innholdskvalitet" }));
    const dialog = await screen.findByRole("dialog", { name: "Analyser innholdskvalitet" });
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Full analyse" })).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Start analyse" }));
    await waitFor(() => expect(server.posted).toEqual([
      { course_id: "101", scope: "course", domains: ["content_quality"], module_ids: [], items: [] }]));
    // The dialog closes, «Analysestatus» opens as the confirmation, and focus is not lost.
    await waitFor(() => expect(panel()).not.toBeNull());
    const busy = screen.getByRole("button", { name: /^Analyse pågår:/ });
    expect(busy).toHaveAttribute("aria-disabled", "true");
    expect(busy).toHaveAccessibleName("Analyse pågår: Henter innhold fra Canvas …");
    expect(busy).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Lukk analysestatus" }));
    await user.click(screen.getByRole("link", { name: "Til Oversikt" }));
    expect(screen.getByRole("button", { name: /^Analyse pågår:/ }), "overlapping: still disabled on Oversikt")
      .toHaveAttribute("aria-disabled", "true");
  }, 15000);

  it("on Oversikt the dialog offers the areas and a full analysis", async () => {
    renderHeader({ path: "/oversikt" });
    await userEvent.click(await screen.findByRole("button", { name: "Analyser hele emnet" }));
    const dialog = await screen.findByRole("dialog", { name: "Analyser hele emnet" });
    expect(within(dialog).getAllByRole("checkbox").length).toBeGreaterThanOrEqual(3);
    expect(within(dialog).getByRole("button", { name: "Full analyse" })).toBeInTheDocument();
  });
});

describe("Analysestatus", () => {
  it("one running job: the button and the panel show the same numbers; only the status control spins", async () => {
    server.jobs = [job()];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 pågår – analysestatus"), WAIT);
    const busy = screen.getByRole("button", { name: /^Analyse pågår:/ });
    expect(busy).toHaveAccessibleName("Analyse pågår: Analyserer innholdet · 124 av 380");
    expect(busy).toHaveAttribute("aria-disabled", "true");
    expect(busy.querySelector(".ek-spinner"), "no spinner in the analysis button").toBeNull();
    expect(spinners()).toHaveLength(1);
    expect(statusControl().contains(spinners()[0])).toBe(true);
    expect(screen.getByRole("button", { name: "Eksporter rapport" })).toBeEnabled();
    expect(screen.getByText(/^Viser resultater fra 6\. november( 2026)? kl\. \d{2}\.42\. Ny kontroll pågår\.$/)).toBeInTheDocument();

    await userEvent.click(busy);
    expect(server.posted, "a disabled button starts nothing").toEqual([]);
    expect(screen.queryByRole("dialog")).toBeNull();

    await userEvent.click(statusControl());
    const region = panel()!;
    expect(statusControl()).toHaveAttribute("aria-expanded", "true");
    expect(spinners(), "with the panel open the bars show the activity – no spinner").toHaveLength(0);
    const row = within(region).getByText("Innholdskvalitet").closest("li")!;
    expect(within(row).getByText("Pågår")).toBeInTheDocument();
    expect(within(row).getByText("124 av 380 lenker")).toBeInTheDocument();
    expect(within(row).getByText("32 %")).toBeInTheDocument();
    expect(within(row).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "32");

    server.jobs = [job({ progress: progress({ types: LINKS(200), version: 2 }) })];
    await waitFor(() => expect(within(region).getByText("200 av 380 lenker")).toBeInTheDocument(), WAIT);
    expect(busy).toHaveAccessibleName("Analyse pågår: Analyserer innholdet · 200 av 380");
  }, 15000);

  it("a new job opens the panel once without taking focus; another course is named; progress does not reopen it", async () => {
    server.jobs = [job({ id: "other", course_id: "202", params: { course_id: "202", domains: ["structure"], scope: "course" } })];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 pågår – analysestatus"), WAIT);
    expect(panel()).toBeNull();
    expect(screen.getByRole("button", { name: "Analyser innholdskvalitet" }), "another course does not block").toBeEnabled();
    const other = screen.getByRole("button", { name: "Eksporter rapport" });
    other.focus();

    server.jobs = [job({ id: "quiz", kind: "quiz_review", title: "Kvalitetssjekk av quiz", params: { quiz_id: "5" },
      progress: progress({ phase: "review", phase_label: "Kvalitetssjekk av quiz", phase_index: 1, phase_count: 1, determinate: false }) }),
    ...server.jobs];
    await waitFor(() => expect(panel()).not.toBeNull(), WAIT);
    expect(other).toHaveFocus();
    expect(statusControl()).toHaveAccessibleName("2 pågår – analysestatus");
    expect(within(panel()!).getByText("Emne: MAT202")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyser innholdskvalitet" }), "a quiz check is independent").toBeEnabled();
    expect(document.querySelectorAll(".ek-job .ek-spinner")).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "Lukk analysestatus" }));
    server.jobs = server.jobs.map((j) => ({ ...j, progress: { ...j.progress, version: 5 } }));
    await new Promise((r) => setTimeout(r, 1500));
    expect(panel(), "progress updates never reopen it").toBeNull();
  }, 15000);

  it("unknown total: a moving segment without a value or percentage, then a filled bar once the total is known", async () => {
    server.jobs = [job({ progress: progress({ phase: "discover", phase_label: "Henter innhold fra Canvas", phase_index: 1,
      determinate: false, types: { list: { label: "Innholdslister", total: 9, done: 3, failed: 0 } } }) })];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 pågår – analysestatus"), WAIT);
    await userEvent.click(statusControl());
    const bar = within(panel()!).getByRole("progressbar");
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar.className).toContain("ek-progress--indeterminate");
    expect(within(panel()!).getByText("Antall foreløpig ukjent – 3 av 9 innholdslister ferdig")).toBeInTheDocument();
    expect(within(panel()!).queryByText(/%/)).toBeNull();
    expect(screen.getByRole("button", { name: /^Analyse pågår:/ })).toHaveAccessibleName("Analyse pågår: Henter innhold fra Canvas …");

    server.jobs = [job({ progress: progress({ types: LINKS(19), version: 3 }) })];
    await waitFor(() => expect(within(panel()!).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "5"), WAIT);
  }, 15000);

  it("Escape closes the panel and returns focus to the control; a click outside closes it", async () => {
    server.jobs = [job()];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 pågår – analysestatus"), WAIT);
    const user = userEvent.setup();
    await user.click(statusControl());
    screen.getByRole("button", { name: "Lukk analysestatus" }).focus();
    await user.keyboard("{Escape}");
    expect(panel()).toBeNull();
    expect(statusControl()).toHaveFocus();
    expect(statusControl()).toHaveAttribute("aria-expanded", "false");
    await user.click(statusControl());
    await user.click(screen.getByRole("main"));
    expect(panel()).toBeNull();
  }, 15000);

  it("a failed analysis stays until hidden; «Prøv igjen» replaces its row; «Skjul» deletes nothing", async () => {
    const failed = job({ id: "f", status: "failed", error: "Mistet forbindelsen til Canvas.", finished_at: ago(1),
      params: { course_id: "101", domains: ["accessibility"], scope: "modules", module_ids: ["7"], items: [] } });
    server.jobs = [failed];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 feilet – analysestatus"), WAIT);
    expect(statusControl()).toHaveTextContent("1 feilet");
    expect(statusControl().querySelector(".ek-jobs-button__warn"), "a static warning symbol").not.toBeNull();
    expect(spinners()).toHaveLength(0);
    const user = userEvent.setup();
    await user.click(statusControl());
    expect(within(panel()!).getByText("Ingen analyser pågår")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lukk analysestatus" }));
    expect(statusControl(), "closing the panel does not hide it").toHaveAccessibleName("1 feilet – analysestatus");

    await user.click(statusControl());
    const row = within(panel()!).getByText("Mistet forbindelsen til Canvas.").closest("li")!;
    expect(within(row).getByText("Feilet")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: /Prøv igjen/ }));
    await waitFor(() => expect(server.posted).toEqual([
      { course_id: "101", scope: "modules", domains: ["accessibility"], module_ids: ["7"], items: [] }]));
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 pågår – analysestatus"), WAIT);
    const rows = within(panel()!).getAllByText("Universell utforming – valgte moduler");
    expect(rows, "the new attempt replaces the row").toHaveLength(1);
    expect(rows[0].closest("li")).toHaveTextContent("Pågår");

    // The new attempt fails too: «Skjul» removes it from the overview only.
    server.jobs = server.jobs.map((j) => (j.id === "new-1" ? { ...j, status: "failed", error: "Feil igjen.", finished_at: ago(0) } : j));
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 feilet – analysestatus"), WAIT);
    await user.click(within(panel()!).getByRole("button", { name: /^Skjul/ }));
    expect(statusControl()).toHaveAccessibleName("Analysestatus");
    expect(within(panel()!).getByText("Ingen analyser pågår")).toBeInTheDocument();
    expect(within(panel()!).queryByRole("heading", { name: "Sist fullførte" }), "an empty list: only the sentence").toBeNull();
    expect(within(panel()!).queryByText(/Oppdateres automatisk/)).toBeNull();
    expect(server.methods.filter((m) => m.startsWith("DELETE"))).toEqual([]);
    expect(within(panel()!).getByRole("link", { name: "Jobbhistorikk" })).toHaveAttribute("href", "/rapporter#jobbhistorikk");
  }, 20000);

  it("tidies itself: four finished from the last day; «Fjern fullførte»; ten rows and «Vis alle aktive og uløste»", async () => {
    const done = (id: string, hours: number) => job({ id, status: "completed", created_at: ago(hours + 0.1), finished_at: ago(hours),
      params: { course_id: "101", domains: ["structure"], scope: "modules", module_ids: [id] } });
    server.jobs = [done("1", 1), done("2", 2), done("3", 3), done("4", 4), done("5", 5)];
    server.history = [done("old", 30)];
    renderHeader();
    const user = userEvent.setup();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("Analysestatus"), WAIT);
    await user.click(statusControl());
    await waitFor(() => expect(within(panel()!).getAllByRole("listitem")).toHaveLength(4));
    expect(within(panel()!).getByText("Ingen analyser pågår")).toBeInTheDocument();
    expect(within(panel()!).getByRole("heading", { level: 3, name: "Sist fullførte" })).toBeInTheDocument();
    expect(within(panel()!).getByRole("list", { name: "Sist fullførte" }).children).toHaveLength(4);
    expect(within(panel()!).getByRole("link", { name: "Jobbhistorikk" })).toBeInTheDocument();
    await user.click(within(panel()!).getByRole("button", { name: "Fjern fullførte" }));
    expect(within(panel()!).queryAllByRole("listitem")).toHaveLength(0);
    expect(within(panel()!).queryByRole("button", { name: "Fjern fullførte" }), "nothing left to remove").toBeNull();
    expect(within(panel()!).getByRole("link", { name: "Jobbhistorikk" })).toBeInTheDocument();
    expect(server.methods.filter((m) => m.startsWith("DELETE"))).toEqual([]);

    server.jobs = Array.from({ length: 12 }, (_, i) => job({ id: `x${i}`, status: "failed", error: `Feil ${i}`, finished_at: ago(i + 1),
      params: { course_id: "101", domains: ["accessibility"], scope: "items", items: [{ object_type: "page", object_id: String(i) }] } }));
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("12 feilet – analysestatus"), { timeout: 12000 });
    expect(within(panel()!).getAllByRole("listitem")).toHaveLength(10);
    await user.click(within(panel()!).getByRole("button", { name: "Vis alle aktive og uløste (12)" }));
    expect(within(panel()!).getAllByRole("listitem")).toHaveLength(12);
  }, 25000);

  it("after a restart the history brings back an interrupted job, however old – it is not shown as running", async () => {
    server.history = [job({ id: "old", status: "interrupted", error: "EmneKlar ble avsluttet mens jobben kjørte.",
      created_at: ago(72), finished_at: ago(72) })];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 avbrutt – analysestatus"), WAIT);
    await userEvent.click(statusControl());
    expect(within(panel()!).getByText("EmneKlar ble avsluttet mens jobben kjørte.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyser innholdskvalitet" })).toBeEnabled();
  }, 15000);

  it("lost contact: the control, the button and the results line say the status is unknown", async () => {
    server.jobs = [job()];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 pågår – analysestatus"), WAIT);
    server.fail = true;
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("Ingen kontakt – analysestatus"), WAIT);
    expect(screen.getByRole("button", { name: /^Analyse:/ })).toHaveAccessibleName("Analyse: Ingen kontakt – status ukjent");
    expect(screen.getByText(/Mistet kontakten med EmneKlar – status for den nye kontrollen er ukjent\.$/)).toBeInTheDocument();
    expect(spinners()).toHaveLength(0);
    await userEvent.click(statusControl());
    expect(within(panel()!).getByText("Ukjent status")).toBeInTheDocument();
    expect(within(panel()!).queryByRole("progressbar")).toBeNull();
  }, 15000);

  it("when it finishes: calm «Analysestatus», the button is usable again and the results' time is updated", async () => {
    server.jobs = [job()];
    renderHeader({ resultsAt: null });
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 pågår – analysestatus"), WAIT);
    expect(screen.getByText("Første kontroll pågår.")).toBeInTheDocument();
    server.jobs = [job({ status: "completed", finished_at: new Date().toISOString(), progress: progress({ types: LINKS(380), version: 9 }) })];
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("Analysestatus"), WAIT);
    expect(spinners()).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Analyser innholdskvalitet" })).toBeEnabled();
    expect(screen.queryByText("Første kontroll pågår.")).toBeNull();
    await userEvent.click(statusControl());
    expect(within(panel()!).getByText("Fullført")).toBeInTheDocument();
    expect(within(panel()!).getByText("380 av 380 lenker kontrollert")).toBeInTheDocument();
  }, 15000);

  it("switching course: the button follows the selected course, and the job keeps its course name", async () => {
    server.jobs = [job()];
    renderHeader();
    await waitFor(() => expect(screen.getByRole("button", { name: /^Analyse pågår:/ })).toBeInTheDocument(), WAIT);
    session.current_course_id = "202";
    await waitFor(() => expect(screen.getByRole("button", { name: "Analyser innholdskvalitet" })).toBeEnabled(), WAIT);
    await userEvent.click(statusControl());
    expect(within(panel()!).getByText("Emne: LA101")).toBeInTheDocument();
  }, 15000);

  it("a job the user cancelled counts as «avbrutt» with a static warning symbol until it is hidden", async () => {
    server.jobs = [job({ id: "c", status: "cancelled", finished_at: ago(0.5) })];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 avbrutt – analysestatus"), WAIT);
    expect(statusControl().querySelector(".ek-jobs-button__warn")).not.toBeNull();
    const user = userEvent.setup();
    await user.click(statusControl());
    const row = within(panel()!).getByText(/^Du avbrøt jobben etter 124 av 380 lenker/).closest("li")!;
    expect(within(row).getByText("Avbrutt")).toBeInTheDocument();
    expect(within(panel()!).queryByRole("heading", { name: "Sist fullførte" }), "not a completed job").toBeNull();
    await user.click(within(row).getByRole("button", { name: /^Skjul/ }));
    expect(statusControl()).toHaveAccessibleName("Analysestatus");
  }, 15000);

  it("keyboard: Tab reaches the control, Enter opens the panel, Tab goes into it, Escape closes it and returns focus", async () => {
    server.jobs = [job({ id: "f", status: "failed", error: "Mistet forbindelsen til Canvas.", finished_at: ago(1) })];
    renderHeader();
    await waitFor(() => expect(statusControl()).toHaveAccessibleName("1 feilet – analysestatus"), WAIT);
    const user = userEvent.setup();
    statusControl().focus();
    await user.keyboard("{Enter}");
    expect(panel()).not.toBeNull();
    expect(statusControl()).toHaveAttribute("aria-expanded", "true");
    expect(statusControl(), "opening with the keyboard keeps focus on the control").toHaveFocus();
    await user.tab();
    expect(within(panel()!).getByRole("button", { name: "Lukk analysestatus" })).toHaveFocus();
    await user.tab();
    expect(panel()!.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Escape}");
    expect(panel()).toBeNull();
    expect(statusControl()).toHaveFocus();
    expect(statusControl()).toHaveAttribute("aria-expanded", "false");
  }, 15000);
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Course, SessionData } from "../../core/api/types";
import {
  accessHeadline,
  accessNotes,
  accessSummary,
  capabilityRow,
  connectionStatus,
  courseList,
  courseMeta,
  courseNames,
  grantedIn,
  initialStep,
  readCanvasUrl,
  teachingCourses,
} from "./model";
import { SetupWizard } from "./SetupWizard";

// Simulated responses only: no real Canvas, no real token (the value below is made up for the test).
const TOKEN = "7~testOnlyToken0123456789abcdefghijklmn";
const fresh = (): Pick<SessionData, "setup_completed" | "canvas" | "general" | "regulatory_profile"> => ({
  setup_completed: false,
  canvas: { base_url: null, token_configured: false, identity: null },
  general: { language: "nb", theme: "light", start_page: "oversikt", default_course_id: null, page_size: 25 },
  regulatory_profile: "no-offentlig-2023",
});
const connected = { base_url: "https://hiof.instructure.com", token_configured: true, identity: { id: "42", name: "Kari Lærer" } };
const session = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));
vi.mock("../../core/session", () => ({ useSession: () => session.current }));

const course = (id: string, name: string, code: string, term = "Høst 2026"): Course => ({
  id, name, course_code: code, term_name: term, workflow_state: "available", is_blueprint: false, default_view: null,
  roles: ["teacher"], favorite: false,
});
const LONG = "Digital kompetanse for lærere i grunnskolen – profesjonsfaglig digital kompetanse, del 2";
const COURSES = [course("101", "Digital kompetanse for lærere", "LA101IKT14-1 26H"), course("102", "Mal for digitale emner", "MAL-DIGITAL"),
  course("103", LONG, "PDK2-26H")];
const cap = (key: string, label: string, granted: number, checked = 2, missing_in: string[] = []) => ({ key, label, granted, checked, missing_in });
const brief = (id: string, name: string, course_code: string | null = null) => ({ id, name, course_code, term_name: "Høst 2026" });
const TESTED = {
  ok: true, base_url: "https://hiof.instructure.com", identity: { id: "42", name: "Kari Lærer" }, teaching_courses: 2,
  courses: [brief("101", "Digital kompetanse for lærere", "LA101IKT14-1 26H"), brief("102", "Mal for digitale emner", "MAL-DIGITAL")],
  access: { teaching_courses: 2, checked_courses: 2, checked_in: ["101", "102"], failed_in: [], capabilities: [
    cap("read", "Lese alt innhold i emnet (også upublisert)", 2), cap("pages", "Redigere sider", 1, 2, ["102"]),
    cap("settings", "Endre emneinnstillinger", 0, 2, ["101", "102"])] },
};
const profile = (id: string, title: string, sector: string, legal = true) => ({
  id, title, sector, description: `Beskrivelse av ${title}.`, is_legal_requirement: legal, standard: "Standard X",
  verified_at: "2026-10-06", criteria_count: 48, document_criteria_count: 44,
  legal_basis: [{ title: "Forskrift om universell utforming av IKT-løsninger", url: "https://lovdata.no/x" }],
});
const PROFILES = { selected: "no-offentlig-2023", profiles: [
  profile("no-offentlig-2023", "Norge – lovkrav, offentlig sektor", "public"),
  profile("no-privat-2013", "Norge – lovkrav, privat sektor", "private"),
  profile("wcag22-aa", "WCAG 2.2 AA – anbefalt beste praksis", "best_practice", false)] };

type Reply = { status?: number; body?: unknown; network?: boolean; wait?: Promise<void> };
interface Canvas {
  test?: Reply[];
  save?: Reply;
  courses?: Course[];
  complete?: Reply[];
}
const calls: { method: string; url: string; body: unknown }[] = [];

function serve(canvas: Canvas = {}) {
  const tests = [...(canvas.test ?? [{ body: TESTED }])];
  const completes = [...(canvas.complete ?? [{ body: { ok: true } }])];
  const next = (list: Reply[]) => (list.length > 1 ? list.shift()! : list[0]);
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    let reply: Reply = { body: {} };
    if (url === "/api/canvas/test") reply = next(tests);
    else if (url === "/api/canvas/connection") reply = canvas.save ?? { body: TESTED };
    else if (url.startsWith("/api/courses")) reply = { body: { courses: canvas.courses ?? COURSES } };
    else if (url === "/api/accessibility/profiles") reply = { body: PROFILES };
    else if (url === "/api/setup/complete") reply = next(completes);
    if (reply.wait) await reply.wait;
    if (reply.network) throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200 });
  }));
}

const error = (status: number, code: string, message: string) => ({ status, body: { error: { code, message } } });

async function axeViolations(container: Element) {
  // jsdom has no layout, so colour contrast is checked in a real browser instead (see the setup's a11y run).
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

function Where() {
  const location = useLocation();
  return <p>Åpnet {location.pathname}{location.search}</p>;
}

function show() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/oppsett"]}>
        <Routes>
          <Route path="/oppsett" element={<SetupWizard />} />
          <Route path="/oversikt" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  session.current = fresh();
  calls.length = 0;
});
afterEach(() => vi.unstubAllGlobals());

async function connect(user: ReturnType<typeof userEvent.setup>, url = "hiof.instructure.com/courses/5") {
  await user.type(screen.getByLabelText("Canvas-adresse"), url);
  await user.type(screen.getByLabelText("Tilgangstoken", { exact: true }), TOKEN);
  await user.click(screen.getByRole("button", { name: "Koble til" }));
}

const sectionText = (name: string) => screen.getByRole("heading", { name }).closest("section")!.textContent;
/** What each option in the open list is called: the name, then code and term. */
const optionNames = () => screen.queryAllByRole("option").map((o) => o.getAttribute("aria-label") ?? o.textContent);

/** «Startemne» the way a teacher uses it: click the field, type, and pick from the list. */
async function chooseCourse(user: ReturnType<typeof userEvent.setup>, text: string, option: string) {
  const field = await screen.findByRole("combobox", { name: "Startemne" });
  await user.click(field);
  if (text) await user.type(field, text);
  await user.click(screen.getByRole("option", { name: option }));
}
const items = (list: HTMLElement) => within(list).getAllByRole("listitem").map((li) => li.textContent);

describe("Oppsett i fire steg", () => {
  it("goes from Canvas to a finished setup, with axe-clean steps, and keeps the token out of the browser", async () => {
    serve();
    const user = userEvent.setup();
    const { container } = show();
    expect(screen.getByRole("heading", { level: 1, name: "Steg 1 av 4: Koble til Canvas" })).toBeInTheDocument();
    const progress = screen.getByRole("navigation", { name: "Steg i oppsettet" });
    expect(progress).toHaveTextContent(/Tilkobling.*Bekreftelse.*Emne og regelverk.*Ferdig/);
    expect(within(progress).getAllByRole("listitem")[0], "the current step is announced").toHaveAttribute("aria-current", "step");
    expect(screen.queryByRole("button", { name: "Tilbake" }), "no back button on the first step").toBeNull();
    const help = screen.getByRole("button", { name: "Slik finner du tilgangstokenet" });
    expect(help).toHaveAttribute("aria-expanded", "false");
    await user.click(help);
    expect(help).toHaveAttribute("aria-expanded", "true");
    expect(await axeViolations(container), "step 1").toEqual([]);

    await connect(user);
    expect(await screen.findByRole("heading", { level: 1, name: "Steg 2 av 4: Bekreft tilkoblingen" })).toHaveFocus();
    expect(within(progress).getAllByRole("listitem")[0]).toHaveTextContent("Tilkobling (fullført)");
    const status = screen.getByText("Tilkoblingen virker, men noen tilganger mangler.").closest(".ek-alert")!;
    expect(status, "a soft warning – not a failed connection").toHaveAttribute("data-tone", "warning");
    expect(status, "the title says it all").toHaveTextContent(/^Tilkoblingen virker, men noen tilganger mangler\.$/);
    expect(screen.getByRole("button", { name: "Bekreft og fortsett" }), "missing write access blocks nothing").toBeEnabled();
    const who = screen.getByText("Tilkoblet som").closest("dl")!;
    expect(who, "who and where – the courses are not listed here").toHaveTextContent(
      "Tilkoblet somKari LærerCanvas-adressehiof.instructure.com");
    expect(screen.queryByText("Emner")).toBeNull();
    expect(sectionText("Tilganger"), "granted everywhere: the check mark says it, the status is still read out").toContain(
      "Lese og analysere: innvilget");
    expect(screen.getByText("Lese og analysere").parentElement).toHaveTextContent(/^Lese og analysere: innvilget$/);
    expect(sectionText("Tilganger"), "only where something is missing").toContain(
      "Redigere sider: i 1 av 2 emner. Du kan fortsatt analysere der det mangler.");
    expect(sectionText("Tilganger")).not.toMatch(/full lesetilgang|kontrollerte/);
    const all = screen.getByRole("button", { name: "Se alle tilganger (3)" });
    expect(all, "the number is the access points in the list").toHaveAttribute("aria-expanded", "false");
    await user.click(all);
    expect(all).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById(all.getAttribute("aria-controls")!), "the button controls the list it opens")
      .toContainElement(screen.getByText(/tilganger er innvilget/));
    expect(screen.getByText(
      "1 av 3 tilganger er innvilget i begge emnene.")).toBeInTheDocument();
    expect(screen.queryByText(/Unntakene står i listen/)).toBeNull();
    expect(screen.queryByText(/^Kontrollert i/), "one sentence, not two").toBeNull();
    const details = screen.getAllByRole("list").at(-1)!;
    expect(items(details), "a note only where it is missing or varies; the status is still spoken").toEqual([
      "Lese alt innhold i emnet (også upublisert): innvilget",
      "Redigere sider: Innvilget i 1 av 2 emner. Mangler i Mal for digitale emner.",
      "Endre emneinnstillinger: Mangler i begge emnene",
    ]);
    expect(within(details).queryAllByText(/^Innvilget i begge/), "no repeated «Innvilget i begge emnene»").toHaveLength(0);
    expect(await axeViolations(container), "step 2").toEqual([]);

    await user.click(screen.getByRole("button", { name: "Bekreft og fortsett" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Steg 3 av 4: Velg emne og regelverk" })).toHaveFocus();
    expect(screen.queryByText(/Tilkoblet som/), "the identity is not repeated in step 3").toBeNull();
    const field = await screen.findByRole("combobox", { name: "Startemne" });
    expect(field, "one field, closed until it is clicked").toHaveAttribute("aria-expanded", "false");
    expect(field).toHaveAttribute("placeholder", "Velg eller søk etter emne");
    await user.click(field);
    expect(field).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox", { name: "Startemne" })).toBeInTheDocument();
    expect(optionNames(), "the name, then code and term on a smaller line").toEqual([
      "Digital kompetanse for lærere, LA101IKT14-1 26H · Høst 2026", "Mal for digitale emner, MAL-DIGITAL · Høst 2026",
      `${LONG}, PDK2-26H · Høst 2026`]);
    expect(await axeViolations(container), "step 3 with the list open").toEqual([]);
    await user.type(field, "pdk2");
    expect(optionNames(), "searched by code").toEqual([`${LONG}, PDK2-26H · Høst 2026`]);
    expect(screen.getByRole("option").querySelector("mark"), "the match is marked").toHaveTextContent("PDK2");
    await user.keyboard("{Enter}");
    expect(field, "chosen: the list closes").toHaveAttribute("aria-expanded", "false");
    expect(field).toHaveValue(LONG);
    expect(screen.getByText(LONG, { selector: ".ek-combobox__value .ek-combobox__label" }),
      "the whole long name is shown in the field (it wraps; nothing is cut)").toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Fjern valgt emne" }));
    expect(field, "× empties the choice").toHaveValue("");
    expect(field).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(field, "↓ opens the list").toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{ArrowDown}{ArrowUp}{Enter}");
    expect(field, "↑/↓ move, Enter chooses").toHaveValue("Digital kompetanse for lærere");
    const offentlig = await screen.findByRole("radio", { name: "Norge – lovkrav, offentlig sektor" });
    expect(offentlig).toBeChecked();
    expect(offentlig, "one text – no separate recommendation line").toHaveAccessibleDescription(
      "Lovkravene for offentlige virksomheter – anbefalt for statlige universiteter og høgskoler.");
    await user.click(screen.getByRole("button", { name: "Vis detaljer om Norge – lovkrav, privat sektor" }));
    expect(offentlig, "«Vis detaljer» does not choose another profile").toBeChecked();
    expect(screen.getByRole("group", { name: "Regelverksprofil" })).toBeInTheDocument();
    expect(await axeViolations(container), "step 3").toEqual([]);
    await user.click(screen.getByRole("button", { name: "Fullfør oppsett" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Steg 4 av 4: Klar til bruk" })).toHaveFocus();
    const summary = screen.getByText("Startemne").closest("dl")!;
    expect(within(summary).getByText("Digital kompetanse for lærere")).toHaveClass("ek-setup__course");
    expect(within(summary).getByText("LA101IKT14-1 26H · Høst 2026"), "code and term on their own muted line").toHaveClass("ek-setup__meta");
    expect(summary).toHaveTextContent("Valgt regelverksprofilNorge – lovkrav, offentlig sektor");
    expect(screen.getByText(/^Du er klar til å åpne emneoversikten\./)).not.toHaveTextContent(/Innstillinger/);
    const actions = screen.getByRole("button", { name: "Åpne emneoversikten" }).parentElement!;
    expect(within(actions).getAllByRole("button").map((b) => b.textContent), "«Tilbake» beside the main button")
      .toEqual(["Tilbake: endre startemne og regelverksprofil", "Åpne emneoversikten"]);
    expect(document.body.textContent, "the token is never shown").not.toContain(TOKEN);
    expect(JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })).not.toContain(TOKEN);
    expect(calls.some((c) => /analysis|\/ai\//.test(c.url)), "no analysis or AI is started").toBe(false);
    expect(await axeViolations(container), "step 4").toEqual([]);
    await user.click(screen.getByRole("button", { name: "Åpne emneoversikten" }));
    expect(await screen.findByText("Åpnet /oversikt")).toBeInTheDocument();
  });

  it("has no «Avslutt EmneKlar» of its own: the setup is a window that can simply be closed", async () => {
    serve();
    show();
    expect(await screen.findByLabelText("Canvas-adresse")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Avslutt EmneKlar" })).not.toBeInTheDocument();
  });

  it("lets the teacher change the choices from the summary, saves them again, and never shows a failed save as saved", async () => {
    session.current = { ...fresh(), canvas: connected };
    serve({ complete: [{ body: { ok: true } }, error(500, "internal_error", "Noe gikk galt."), { body: { ok: true } }] });
    const user = userEvent.setup();
    show();
    await chooseCourse(user, "", "Digital kompetanse for lærere, LA101IKT14-1 26H · Høst 2026");
    await user.click(await screen.findByRole("button", { name: "Fullfør oppsett" }));
    await screen.findByRole("heading", { name: /Klar til bruk/ });

    await user.click(screen.getByRole("button", { name: "Tilbake: endre startemne og regelverksprofil" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Velg emne og regelverk/ })).toHaveFocus();
    expect(screen.getByRole("combobox", { name: "Startemne" }), "the choices are kept").toHaveValue("Digital kompetanse for lærere");
    expect(screen.getByRole("radio", { name: "Norge – lovkrav, offentlig sektor" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "WCAG 2.2 AA – anbefalt beste praksis" }));
    await user.click(screen.getByRole("button", { name: "Fullfør oppsett" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Endringene ble ikke lagret.*Valgene som ble lagret tidligere, gjelder fortsatt\./);
    expect(screen.getByRole("heading", { level: 1 }), "a failed save is not shown as saved").toHaveTextContent("Velg emne og regelverk");

    await user.click(screen.getByRole("button", { name: "Avbryt endringen" }));
    const summary = (await screen.findByText("Startemne")).closest("dl")!;
    expect(summary, "the summary shows what was actually saved").toHaveTextContent("Norge – lovkrav, offentlig sektor");

    await user.click(screen.getByRole("button", { name: "Tilbake: endre startemne og regelverksprofil" }));
    expect(screen.getByRole("radio", { name: "Norge – lovkrav, offentlig sektor" }), "cancelling restored the saved choice").toBeChecked();
    await user.click(screen.getByRole("button", { name: "Fjern valgt emne" })); // choose later
    await user.click(screen.getByRole("radio", { name: "WCAG 2.2 AA – anbefalt beste praksis" }));
    await user.click(screen.getByRole("button", { name: "Fullfør oppsett" }));
    const saved = (await screen.findByText("Startemne")).closest("dl")!;
    expect(saved).toHaveTextContent("StartemneVelges senere");
    expect(saved).toHaveTextContent("WCAG 2.2 AA – anbefalt beste praksis");
    expect(calls.filter((c) => c.url === "/api/setup/complete").map((c) => c.body)).toEqual([
      { default_course_id: "101", regulatory_profile: "no-offentlig-2023" },
      { default_course_id: "101", regulatory_profile: "wcag22-aa" },
      { default_course_id: null, regulatory_profile: "wcag22-aa" },
    ]);
    expect(calls.some((c) => c.url.startsWith("/api/canvas/")), "no new connection check, no token").toBe(false);
    expect(screen.getByText(/^Du er klar til å velge emne\./)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Velg emne" }));
    expect(await screen.findByText("Åpnet /oversikt?velg-emne=1")).toBeInTheDocument();
  });

  it("counts the access points it shows, and keeps granted, partial, missing and unknown apart", async () => {
    const codes = ["A1", "B2", "C3", "D4"];
    const seven = [brief("A1", "Kjemi 1", "KJ1-H"), brief("B2", "Kjemi 1", "KJ1-V"), brief("C3", "Fysikk"), brief("D4", "Biologi"),
      brief("E5", "Geologi"), brief("F6", "Astronomi"), brief("G7", "Matematikk")];
    const five = { ...TESTED, teaching_courses: 7, courses: seven, access: { teaching_courses: 7, checked_courses: 4, checked_in: codes,
      failed_in: ["E5"], capabilities: [
        cap("read", "Lese", 4, 4), cap("pages", "Redigere sider", 4, 4), cap("modules", "Moduler", 2, 4, ["C3", "D4"]),
        cap("settings", "Innstillinger", 0, 4, codes), cap("quizzes", "Quizer", 0, 0)] } };
    serve({ test: [{ body: five }] });
    const user = userEvent.setup();
    show();
    await connect(user);
    await screen.findByText("Tilkoblet som");
    expect(sectionText("Tilganger")).toContain("Lese og analysere: innvilget");
    expect(sectionText("Tilganger")).toContain("Redigere sider: innvilget");
    await user.click(screen.getByRole("button", { name: "Se alle tilganger (5)" }));
    expect(screen.getByText("2 av 5 tilganger er innvilget i alle 4 kontrollerte emner."),
      "many courses: a short sentence, the names on request").toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vis emnene (4)" }));
    expect(screen.getByText("Fysikk", { selector: ".ek-setup__names.ek-small li" })).toBeVisible();
    expect(screen.getByText("Kunne ikke kontrolleres i Geologi."), "a course that could not be checked is unknown, not missing").toBeInTheDocument();
    expect(screen.getByText("Kontrollen gjelder et utvalg på 5 av 7 emner.")).toBeInTheDocument();
    expect(items(screen.getAllByRole("list").at(-1)!)).toEqual([
      "Lese: innvilget",
      "Redigere sider: innvilget",
      "Moduler: Innvilget i 2 av 4 kontrollerte emner. Mangler i Fysikk og Biologi.",
      "Innstillinger: Mangler i alle 4 kontrollerte emner",
      "Quizer: Kunne ikke kontrolleres",
    ]);
    const box = screen.getByText(/^Tilkoblingen virker/).closest(".ek-alert")!;
    expect(box).toHaveAttribute("data-tone", "warning");
    expect(box).toHaveTextContent("Tilkoblingen virker, men noen tilganger mangler, og enkelte kunne ikke kontrolleres.");
  });

  it("says once that everything is granted when it is", async () => {
    const granted = { ...TESTED, access: { ...TESTED.access,
      capabilities: TESTED.access.capabilities.map((c) => ({ ...c, granted: 2, missing_in: [] })) } };
    serve({ test: [{ body: granted }] });
    const user = userEvent.setup();
    show();
    await connect(user);
    await user.click(await screen.findByRole("button", { name: "Se alle tilganger (3)" }));
    expect(screen.getByText("Alle kontrollerte tilganger er innvilget i Digital kompetanse for lærere og Mal for digitale emner."))
      .toBeInTheDocument();
    expect(screen.getByText("Tilkoblingen virker.").closest(".ek-alert")).toHaveAttribute("data-tone", "success");
    expect(items(screen.getAllByRole("list").at(-1)!).every((t) => t?.endsWith(": innvilget"))).toBe(true);
  });

  it("names the one course in the access details when there is one", async () => {
    const one = { ...TESTED, teaching_courses: 1, courses: [TESTED.courses[0]], access: { teaching_courses: 1, checked_courses: 1,
      checked_in: ["101"], failed_in: [], capabilities: [cap("read", "Lese", 1, 1), cap("pages", "Redigere sider", 1, 1)] } };
    serve({ test: [{ body: one }] });
    const user = userEvent.setup();
    show();
    await connect(user);
    await user.click(await screen.findByRole("button", { name: "Se alle tilganger (2)" }));
    expect(screen.getByText("Alle kontrollerte tilganger er innvilget i Digital kompetanse for lærere.")).toBeInTheDocument();
  });

  it("has an eye button inside the token field that shows and hides the token without submitting", async () => {
    serve();
    const user = userEvent.setup();
    show();
    const field = screen.getByLabelText("Tilgangstoken", { exact: true });
    await user.type(field, TOKEN);
    expect(field, "hidden by default").toHaveAttribute("type", "password");
    const eye = screen.getByRole("button", { name: "Vis tilgangstoken" });
    expect(eye).toHaveAttribute("type", "button");
    expect(eye.closest(".ek-input-affix")).toContainElement(field);
    eye.focus();
    await user.keyboard("{Enter}");
    expect(field).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Skjul tilgangstoken" })).toHaveFocus();
    await user.keyboard(" ");
    expect(field).toHaveAttribute("type", "password");
    expect(field, "the token is kept").toHaveValue(TOKEN);
    expect(calls, "the button never submits the form").toHaveLength(0);
  });

  it("says «Kobler til …» while checking and never sends twice", async () => {
    let release = () => {};
    const wait = new Promise<void>((resolve) => { release = resolve; });
    serve({ test: [{ body: TESTED, wait }] });
    const user = userEvent.setup();
    show();
    await connect(user);
    const busy = screen.getByRole("button", { name: /Kobler til/ });
    expect(busy).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Kobler til …");
    await user.keyboard("{Enter}");
    await user.click(busy);
    expect(calls.filter((c) => c.url === "/api/canvas/test")).toHaveLength(1);
    release();
    expect(await screen.findByRole("heading", { level: 1, name: /Bekreft tilkoblingen/ })).toBeInTheDocument();
  });

  it("shows what is wrong at the field, and keeps what was typed when the network fails", async () => {
    serve({ test: [error(401, "canvas_token_invalid", "Canvas avviste tokenet."), { network: true }] });
    const user = userEvent.setup();
    show();
    await user.click(screen.getByRole("button", { name: "Koble til" }));
    expect(screen.getByLabelText("Canvas-adresse")).toHaveAccessibleDescription(/Skriv inn adressen til Canvas\./);
    expect(screen.getByLabelText("Canvas-adresse"), "focus goes to the first field with an error").toHaveFocus();
    expect(calls).toHaveLength(0);

    await connect(user, "https://hiof.instructure.com");
    expect(await screen.findByText("Canvas avviste tokenet.")).toBeInTheDocument();
    const token = screen.getByLabelText("Tilgangstoken", { exact: true });
    expect(token).toHaveAttribute("aria-invalid", "true");
    expect(token).toHaveAccessibleDescription(/Canvas avviste tokenet\./);
    expect(token).toHaveFocus();

    await user.type(token, "x");
    await user.click(screen.getByRole("button", { name: "Koble til" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Kunne ikke koble til.*Fikk ikke kontakt.*Det du har skrevet inn, er beholdt\./);
    expect(screen.getByLabelText("Canvas-adresse")).toHaveValue("https://hiof.instructure.com");
    expect(token).toHaveValue(`${TOKEN}x`);
  });

  it("throws away the earlier check when the token changes, and keeps the choices when going back", async () => {
    serve();
    const user = userEvent.setup();
    show();
    await connect(user);
    await screen.findByRole("heading", { name: /Bekreft tilkoblingen/ });
    await user.click(screen.getByRole("button", { name: "Tilbake" }));
    expect(screen.getByLabelText("Canvas-adresse"), "the address is kept").toHaveValue("https://hiof.instructure.com");
    await user.type(screen.getByLabelText("Tilgangstoken", { exact: true }), "2");
    await user.click(screen.getByRole("button", { name: "Koble til" }));
    await screen.findByRole("heading", { name: /Bekreft tilkoblingen/ });
    expect(calls.filter((c) => c.url === "/api/canvas/test")[1].body).toMatchObject({ token: `${TOKEN}2` });

    await user.click(screen.getByRole("button", { name: "Bekreft og fortsett" }));
    await user.click(await screen.findByRole("radio", { name: "WCAG 2.2 AA – anbefalt beste praksis" }));
    await chooseCourse(user, "mal", "Mal for digitale emner, MAL-DIGITAL · Høst 2026");
    await user.click(screen.getByRole("button", { name: "Tilbake" }));
    await user.click(await screen.findByRole("button", { name: "Bekreft og fortsett" }));
    expect(await screen.findByRole("radio", { name: "WCAG 2.2 AA – anbefalt beste praksis" }), "not reset to the default").toBeChecked();
    expect(screen.getByRole("combobox", { name: "Startemne" })).toHaveValue("Mal for digitale emner");
    expect(calls.filter((c) => c.url === "/api/canvas/connection"), "a saved connection is not sent again").toHaveLength(1);
  });

  it("saves nothing when the token now belongs to someone else, and keeps an earlier connection when saving fails", async () => {
    serve({ save: error(409, "canvas_identity_changed", "Tokenet hører nå til en annen Canvas-bruker.") });
    const user = userEvent.setup();
    const first = show();
    await connect(user);
    await user.click(await screen.findByRole("button", { name: "Bekreft og fortsett" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/annen Canvas-bruker.*Velg «Tilbake» og koble til på nytt\./);
    expect(screen.getByRole("button", { name: "Bekreft og fortsett" })).toBeDisabled();
    first.unmount();

    serve({ save: error(500, "secret_store_unavailable", "Kunne ikke lagre i Windows Legitimasjonsbehandling.") });
    show();
    await connect(user);
    await user.click(await screen.findByRole("button", { name: "Bekreft og fortsett" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Kunne ikke lagre.*En tidligere lagret tilkobling er ikke endret\./);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Bekreft tilkoblingen");
  });

  it("never reuses a stored token for another Canvas address", async () => {
    session.current = { ...fresh(), canvas: { base_url: "https://hiof.instructure.com", token_configured: true, identity: null } };
    serve();
    const user = userEvent.setup();
    show();
    expect(screen.getByLabelText("Tilgangstoken", { exact: true })).toHaveAccessibleDescription(/lagret for denne adressen/);
    await user.clear(screen.getByLabelText("Canvas-adresse"));
    await user.type(screen.getByLabelText("Canvas-adresse"), "https://annen.instructure.com");
    await user.click(screen.getByRole("button", { name: "Koble til" }));
    expect(screen.getByLabelText("Tilgangstoken", { exact: true })).toHaveAccessibleDescription(/hører til en annen Canvas-adresse/);
    expect(calls).toHaveLength(0);
  });

  it("resumes an interrupted setup at «Emne og regelverk», keeps the stored profile and handles no courses", async () => {
    session.current = { ...fresh(), canvas: connected, regulatory_profile: "no-privat-2013" };
    serve({ courses: [] });
    show();
    expect(screen.getByRole("heading", { level: 1, name: "Steg 3 av 4: Velg emne og regelverk" })).toBeInTheDocument();
    expect(await screen.findByText(/Fant ingen emner der du er lærer/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox"), "nothing to choose from: no field").toBeNull();
    expect(await screen.findByRole("radio", { name: "Norge – lovkrav, privat sektor" }), "an existing choice is kept").toBeChecked();
  });

  it("can go back to «Bekreftelse» in a resumed setup: the saved connection is checked again, nothing is saved", async () => {
    session.current = { ...fresh(), canvas: connected };
    serve();
    const user = userEvent.setup();
    show();
    await screen.findByRole("heading", { level: 1, name: /Velg emne og regelverk/ });
    const progress = screen.getByRole("navigation", { name: "Steg i oppsettet" });
    await user.click(within(progress).getByRole("button", { name: /^Bekreftelse/ }));
    expect(await screen.findByRole("heading", { level: 1, name: /Bekreft tilkoblingen/ })).toHaveFocus();
    expect(calls.filter((c) => c.url === "/api/canvas/test").map((c) => c.body), "the stored token, only a check").toEqual([
      { base_url: "https://hiof.instructure.com", token: null, capabilities: true }]);
    await user.click(screen.getByRole("button", { name: "Bekreft og fortsett" }));
    await screen.findByRole("heading", { level: 1, name: /Velg emne og regelverk/ });
    expect(calls.filter((c) => c.url === "/api/canvas/connection"), "already saved: not sent again").toHaveLength(0);
  });

  it("preselects the public-sector profile when nothing usable is stored", async () => {
    session.current = { ...fresh(), canvas: connected, regulatory_profile: "en-profil-som-ikke-finnes" };
    serve();
    show();
    expect(await screen.findByRole("radio", { name: "Norge – lovkrav, offentlig sektor" })).toBeChecked();
  });

  it("searches all the courses in one field – by name, code or term – and says when nothing matches", async () => {
    session.current = { ...fresh(), canvas: connected };
    const many = Array.from({ length: 76 }, (_, i) => course(String(200 + i), i === 70 ? "Kjemi for lærere" : `Emne ${i}`,
      i === 3 ? "Emne 3" : `E${i}`, i === 50 ? "Vår 2027" : "Høst 2026"));
    serve({ courses: many });
    const user = userEvent.setup();
    show();
    const field = await screen.findByRole("combobox", { name: "Startemne" });
    await user.click(field);
    expect(optionNames(), "every course is in the list; it scrolls").toHaveLength(76);
    expect(optionNames(), "a code that only repeats the name is left out").toContain("Emne 3, Høst 2026");
    await user.type(field, "kjemi");
    expect(optionNames()).toEqual(["Kjemi for lærere, E70 · Høst 2026"]);
    expect(screen.getByText("1 treff.")).toHaveAttribute("role", "status");
    await user.clear(field);
    await user.type(field, "vår 2027");
    expect(optionNames(), "by term").toEqual(["Emne 50, E50 · Vår 2027"]);
    await user.clear(field);
    await user.type(field, "fysikk");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getAllByText("Fant ingen emner som passer").length, "said in the list and read out").toBe(2);
    await user.keyboard("{Escape}");
    expect(field, "Esc closes").toHaveAttribute("aria-expanded", "false");
    expect(field).toHaveValue("");
  });

  it("has «Tilbake» on every card after the first, and goes to any step already reached from the steps at the top", async () => {
    serve();
    const user = userEvent.setup();
    show();
    const progress = screen.getByRole("navigation", { name: "Steg i oppsettet" });
    const stepButton = (name: RegExp) => within(progress).getByRole("button", { name });
    expect(stepButton(/^Bekreftelse/), "not before there is something to confirm").toBeDisabled();
    expect(stepButton(/^Emne og regelverk/)).toBeDisabled();
    await connect(user);
    await screen.findByRole("heading", { level: 1, name: /Bekreft tilkoblingen/ });
    expect(stepButton(/^Emne og regelverk/), "not before the connection is confirmed").toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Bekreft og fortsett" }));
    await screen.findByRole("heading", { level: 1, name: /Velg emne og regelverk/ });
    await chooseCourse(user, "mal", "Mal for digitale emner, MAL-DIGITAL · Høst 2026");
    await user.click(screen.getByRole("button", { name: "Fullfør oppsett" }));
    await screen.findByRole("heading", { level: 1, name: /Klar til bruk/ });

    await user.click(stepButton(/^Tilkobling/));
    expect(await screen.findByRole("heading", { level: 1, name: /Koble til Canvas/ }), "straight back to the start").toHaveFocus();
    expect(screen.getByLabelText("Canvas-adresse")).toHaveValue("https://hiof.instructure.com");
    await user.click(stepButton(/^Ferdig/));
    expect(await screen.findByRole("heading", { level: 1, name: /Klar til bruk/ })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: /^Tilbake/ }));
    await screen.findByRole("heading", { level: 1, name: /Velg emne og regelverk/ });
    expect(screen.getByRole("combobox", { name: "Startemne" })).toHaveValue("Mal for digitale emner");
    await user.click(screen.getByRole("button", { name: "Tilbake" }));
    await screen.findByRole("heading", { level: 1, name: /Bekreft tilkoblingen/ });
    await user.click(screen.getByRole("button", { name: "Tilbake" }));
    await screen.findByRole("heading", { level: 1, name: /Koble til Canvas/ });
    expect(screen.queryByRole("button", { name: "Tilbake" }), "nothing before the first step").toBeNull();
    expect(calls.filter((c) => c.url === "/api/canvas/connection"), "going back saves nothing again").toHaveLength(1);
    expect(calls.filter((c) => c.url === "/api/setup/complete")).toHaveLength(1);
  });
});

describe("oppsettets regler", () => {
  it("starts where an interrupted setup left off, and never forces a finished setup through again", () => {
    expect(initialStep(fresh())).toBe("connect");
    const saved = { base_url: "https://x.no", token_configured: true, identity: { id: "1", name: "A" } };
    expect(initialStep({ setup_completed: false, canvas: saved })).toBe("start");
    expect(initialStep({ setup_completed: false, canvas: { ...saved, token_configured: false } })).toBe("connect");
    expect(initialStep({ setup_completed: true, canvas: saved })).toBe("connect");
  });

  it("reads the Canvas address the way Canvas needs it", () => {
    expect(readCanvasUrl("hiof.instructure.com")).toEqual({ url: "https://hiof.instructure.com" });
    expect(readCanvasUrl(" https://hiof.instructure.com/courses/547/pages/x ")).toEqual({ url: "https://hiof.instructure.com" });
    expect(readCanvasUrl("")).toEqual({ error: "Skriv inn adressen til Canvas." });
    expect(readCanvasUrl("ftp://hiof.no")).toMatchObject({ error: expect.stringContaining("https://") });
    expect(readCanvasUrl("https://bruker:passord@hiof.no")).toMatchObject({ error: expect.stringContaining("brukernavn") });
    expect(readCanvasUrl("canvas")).toMatchObject({ error: expect.stringContaining("hele adressen") });
  });

  it("words the numbers naturally – one, two and more – and never generalises", () => {
    expect([0, 1, 2, 9].map(teachingCourses)).toEqual([
      "Ingen emner med lærer-, assistent- eller designertilgang", "1 emne med lærer-, assistent- eller designertilgang",
      "2 emner med lærer-, assistent- eller designertilgang", "9 emner med lærer-, assistent- eller designertilgang"]);
    expect(grantedIn({ granted: 1, checked: 1 })).toBe("i det kontrollerte emnet");
    expect(grantedIn({ granted: 2, checked: 2 })).toBe("i begge kontrollerte emner");
    expect(grantedIn({ granted: 5, checked: 5 })).toBe("i alle 5 kontrollerte emner");
    expect(grantedIn({ granted: 3, checked: 5 })).toBe("i 3 av 5 kontrollerte emner");
    expect(grantedIn({ granted: 0, checked: 2 })).toBe("i ingen av de to kontrollerte emnene");
    expect(grantedIn({ granted: 0, checked: 1 })).toBe("ikke i det kontrollerte emnet");
    expect([[2, 2, 2], [3, 5, 5], [0, 2, 2], [0, 1, 1], [1, 1, 1]].map(([granted, checked, teaching]) =>
      grantedIn({ granted, checked }, teaching)), "every course checked: no «kontrollerte»").toEqual([
      "i begge emnene", "i 3 av 5 emner", "i ingen av de to emnene", "ikke i emnet", "i emnet"]);
    expect(grantedIn({ granted: 2, checked: 2 }, 3), "a sample: says «kontrollerte»").toBe("i begge kontrollerte emner");
    const one = (granted: number, missing: string[] = []) => ({ key: "k", label: "L", granted, checked: 1, missing_in: missing });
    expect(capabilityRow(one(0, ["PDK2-26H"])).note).toBe("Mangler i PDK2-26H");
    expect(capabilityRow(one(1))).toEqual({ level: "all", note: null, spoken: "innvilget" });
    expect(capabilityRow({ key: "k", label: "L", granted: 2, checked: 3, missing_in: ["PDK2-26H"] }).note)
      .toBe("Innvilget i 2 av 3 kontrollerte emner. Mangler i PDK2-26H.");
    expect(capabilityRow({ key: "k", label: "L", granted: 2, checked: 3, missing_in: ["PDK2-26H"] }, undefined, 3, 3).note)
      .toBe("Innvilget i 2 av 3 emner. Mangler i PDK2-26H.");
    expect(capabilityRow({ key: "k", label: "L", granted: 0, checked: 3, missing_in: [] }, undefined, 3, 5).note)
      .toBe("Mangler i alle 3 kontrollerte emner");
    expect(accessHeadline({ teaching_courses: 1, checked_courses: 1, capabilities: [one(1)] }).text, "without names").toBe(
      "Alle kontrollerte tilganger er innvilget i emnet.");
    expect(accessHeadline({ teaching_courses: 3, checked_courses: 0, capabilities: [] }).text).toBe("Tilgangene kunne ikke kontrolleres.");
    const two = (granted: number) => ({ key: "k", label: "L", granted, checked: 2, missing_in: granted === 2 ? [] : ["2"] });
    const partial = (teaching: number, checked: number) => ({ teaching_courses: teaching, checked_courses: checked,
      checked_in: ["1", "2"].slice(0, checked), capabilities: [two(2), two(2), two(1)] });
    expect(accessHeadline(partial(2, 2)).text).toBe("2 av 3 tilganger er innvilget i begge emnene.");
    expect(accessHeadline(partial(3, 2)), "not all courses checked: says «kontrollerte» and offers the names").toEqual({
      text: "2 av 3 tilganger er innvilget i begge kontrollerte emner.", courses: ["1", "2"] });
    const single = { teaching_courses: 1, checked_courses: 1, checked_in: ["1"], capabilities: [one(1), one(0)] };
    expect(accessHeadline(single).text).toBe("1 av 2 tilganger er innvilget i emnet.");
    expect(connectionStatus(single)).toEqual({ tone: "warning", title: "Tilkoblingen virker, men noen tilganger mangler." });
    expect(connectionStatus({ teaching_courses: 2, checked_courses: 1, checked_in: ["1"], failed_in: ["2"], capabilities: [one(1)] }))
      .toEqual({ tone: "warning", title: "Tilkoblingen virker, men enkelte tilganger kunne ikke kontrolleres." });
    expect(connectionStatus({ teaching_courses: 1, checked_courses: 1, capabilities: [one(1)] }).tone).toBe("success");
    expect(connectionStatus({ teaching_courses: 0, checked_courses: 0, capabilities: [] }), "no courses is not an error").toEqual({
      tone: "success", title: "Tilkoblingen virker." });
    expect(accessNotes({ teaching_courses: 1, checked_courses: 0, failed_in: ["X"], capabilities: [] })).toEqual([
      "Kunne ikke kontrolleres i X."]);
    const name = courseNames([brief("1", "Kjemi", "K-H"), brief("2", "kjemi ", "K-V"), brief("3", "", "UTEN-NAVN"), brief("4", "Fysikk")]);
    expect(["1", "2", "3", "4", "9"].map(name), "a code only for alike names; ids of unknown courses stay ids").toEqual([
      "Kjemi (K-H)", "kjemi (K-V)", "UTEN-NAVN", "Fysikk", "9"]);
    expect([["A"], ["A", "B"], ["A", "B", "C"], ["A", "B", "C", "D", "E"]].map(courseList)).toEqual([
      "A", "A og B", "A, B og C", "A, B, C og 2 til"]);
    const none = accessSummary({ teaching_courses: 3, checked_courses: 3, capabilities: [
      { key: "read", label: "Lese", granted: 3, checked: 3 }, { key: "pages", label: "Sider", granted: 0, checked: 3 }] });
    expect(none.map((l) => [l.title, l.level])).toEqual([["Lese og analysere", "all"], ["Redigere sider", "none"]]);
    expect(none[1].text, "missing write access does not block analysis").toBe(
      "i ingen av de 3 emnene. Du kan fortsatt analysere der det mangler.");
    expect(accessSummary({ teaching_courses: 0, checked_courses: 0, capabilities: [] })[0].text).toMatch(/ingen emner å kontrollere/);
    expect(courseMeta({ course_code: "LA101", term_name: null })).toBe("LA101");
    expect(courseMeta({ name: "Mal for emner", course_code: "mal for emner ", term_name: "Høst 2026" }),
      "the name is not repeated on the smaller line").toBe("Høst 2026");
    expect(accessSummary({ teaching_courses: 2, checked_courses: 2, capabilities: [
      { key: "read", label: "Lese", granted: 2, checked: 2 }, { key: "pages", label: "Sider", granted: 2, checked: 2 }] })
      .map((l) => l.text), "granted everywhere: nothing to add").toEqual(["", ""]);
  });
});

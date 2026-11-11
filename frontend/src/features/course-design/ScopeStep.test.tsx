import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunAnalysisButton } from "../../core/layout/HeaderControls";
import { UiProvider } from "../../core/ui";
import { ToastProvider } from "../../design-system";
import type { InventoryItem, InventoryModule } from "./api";
import { CourseDesign } from "./CourseDesign";
import { moduleMeta, scopeFacts } from "./ScopeStep";

vi.mock("../../core/session", () => ({
  useSession: () => ({ canvas: { token_configured: true }, ai: { providers_enabled: [] }, flags: {}, general: { page_size: 25 } }),
}));
const course = vi.hoisted(() => ({ id: "101" }));
vi.mock("../../core/course", () => ({
  useCurrentCourse: () => ({ courseId: course.id, course: null, loading: false }),
  useCourses: () => ({ data: { courses: [] } }),
}));

const profile = { id: "akademisk", version: "2", label: "Akademisk", description: "Akademisk", default: true, tokens: {},
  sample_keep: "<div class=\"ek-design\"><p>Hele eksemplet</p></div>", sample_structure: "<div class=\"ek-design\">Akademisk</div>",
  sample_title: "Uke 3: Tilbakemelding", sample_compact: "<div class=\"ek-design\"><p>Kort</p></div>" };
const item = (key: string, title: string, kind: string, extra: object = {}): InventoryItem => ({
  key, object_type: key.split(":")[0], object_id: key.split(":")[1], title, kind: kind as InventoryItem["kind"], kind_label: kind,
  modules: ["Modul 1"], shared: false, locked: false, published: true, design: null, empty: false, excluded: false, url: null, ...extra,
});
const MODULES: InventoryModule[] = [
  { id: "201", name: "Modul 1", position: 1, published: true, count: 2, total: 4 },
  { id: "202", name: "Modul 2", position: 2, published: true, count: 1, total: 1 },
];
const COURSE_ITEMS = [
  item("page:forside", "Forside", "front_page"),
  item("page:intro", "Intro", "module_intro", { modules: ["Modul 1", "Modul 2"], shared: true }),
  item("assignment:301", "Innlevering", "assignment", { locked: true }),
  item("page:tom", "Tom side", "page", { empty: true }),
];
const where = { role: "course", message: "Endringen gjøres bare i dette emnet." };
const NOT_INCLUDED = [{ label: "New Quizzes (1)", reason: "Eget API." }, { label: "Canvas' eget grensesnitt", reason: "Endres ikke." }];
const ASSOCIATED = { role: "associated", summary: "Emnet er knyttet til Blueprint-emnet «BP». 1 av 2 elementer i utvalget er låst derfra.",
  limitation: "1 av 2 elementer er låst fra Blueprint-emnet og må trolig endres der.", locked: 1, total: 2,
  details: ["1 av 2 elementer er ikke låst. De endres bare i dette emnet."] };

type Answer = { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>;

function stub(inventory: (moduleId: string | null) => Answer, granted = true) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    let answer: Answer = { body: {} };
    if (url.endsWith("/api/course-design/profiles")) answer = { body: { profiles: [profile], default: "akademisk" } };
    else if (url.endsWith("/course-design")) answer = { body: { design: null, excluded: [] } };
    else if (url.endsWith("/capabilities")) {
      answer = { body: { capabilities: [{ key: "pages", label: "Redigere sider", granted },
        { key: "assignments", label: "Endre oppgaver og klassiske quizer", granted: true }] } };
    } else if (url.includes("/course-design/inventory")) {
      answer = inventory(new URL(url, "http://x").searchParams.get("module_id"));
    }
    const { status = 200, body } = await answer;
    return new Response(JSON.stringify(body), { status });
  }));
  return calls;
}

const full = (moduleId: string | null, extra: object = {}) => ({
  body: { modules: MODULES, where, blueprint: null, course: { name: "Emne" }, not_included: NOT_INCLUDED,
    items: moduleId === "202" ? [COURSE_ITEMS[1]] : moduleId === "201" ? COURSE_ITEMS.slice(1, 3) : COURSE_ITEMS, ...extra },
});

function wrap(children: ReactNode, path = "/emnedesign") {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider><UiProvider><MemoryRouter initialEntries={[path]}>{children}</MemoryRouter></UiProvider></ToastProvider>
    </QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  course.id = "101";
});

describe("counting", () => {
  it("counts unique items once, separates skipped ones and locked ones are part of the total", () => {
    const facts = scopeFacts([...COURSE_ITEMS, item("page:egen", "Egen", "page", { excluded: true })]);
    expect(facts.ready.map((i) => i.key)).toEqual(["page:forside", "page:intro", "assignment:301"]);
    expect([facts.empty, facts.excluded, facts.locked, facts.shared.length]).toEqual([1, 1, 1, 1]);
  });

  it("describes a module, and tells equal names apart by place and publishing", () => {
    const twins: InventoryModule[] = [
      { id: "1", name: "Uke 1", position: 1, published: true, count: 2, total: 5 },
      { id: "2", name: "Uke 1", position: 2, published: false, count: 0, total: 3 },
      { id: "3", name: "Tom", position: 3, published: true, count: 0, total: 0 },
    ];
    expect(moduleMeta(twins[0], twins)).toBe("5 elementer, 2 kan få design · modul 1 av 3");
    expect(moduleMeta(twins[1], twins)).toBe("3 elementer, ingen kan få design · modul 2 av 3 · ikke publisert");
    expect(moduleMeta(twins[2], twins)).toBe("Tom modul");
  });
});

describe("Emnedesign – omfang", () => {
  it("shows the steps in a row, and later steps cannot be skipped to", async () => {
    stub(full);
    render(wrap(<CourseDesign />));
    const nav = screen.getByRole("navigation", { name: "Steg i Emnedesign" });
    expect(within(nav).getAllByRole("button").map((b) => b.textContent)).toEqual(["1Omfang", "2Design", "3Forhåndsvisning", "4Godkjenning"]);
    expect(within(nav).getByText("Steg 1 av 4 – Omfang")).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: /Omfang/ }).closest("li")).toHaveAttribute("aria-current", "step");
    expect(within(nav).getByRole("button", { name: /Forhåndsvisning/ })).toBeDisabled();
    expect(within(nav).getByRole("button", { name: /Godkjenning/ })).toBeDisabled();
    expect(screen.getByText("Gi emnet eller en modul et gjennomført design. Se og godkjenn endringene før de sendes til Canvas.")).toBeInTheDocument();
  });

  it("summarises the whole course from Canvas, with the breakdown and access behind disclosures", async () => {
    stub(full, false);
    const user = userEvent.setup();
    render(wrap(<CourseDesign />));
    expect(screen.getByRole("radio", { name: /Hele emnet/ })).toBeChecked();
    const next = screen.getByRole("button", { name: "Neste: velg design" });
    expect(next, "waits for the content").toBeDisabled();
    const summary = await screen.findByRole("region", { name: "Dette blir berørt" });
    expect(within(summary).getByText("3 innholdselementer – inkludert 1 som er låst fra Blueprint-emnet")).toBeInTheDocument();
    expect(within(summary).getByText("1 tomt element")).toBeInTheDocument();
    expect(within(summary).getByText("New Quizzes (1) – støttes ikke av Emnedesign")).toBeInTheDocument();
    expect(await within(summary).findByText(/Du mangler tilgang i Canvas til å redigere sider\. 1 av 3 kan endres med dine rettigheter\./)).toBeInTheDocument();
    await user.click(within(summary).getByText("Se fordeling"));
    const table = within(summary).getByRole("table");
    expect(within(table).getAllByRole("row").map((r) => r.textContent)).toEqual(["Forside1", "Modulintroduksjoner1", "Oppgaver1", "Til sammen3"]);
    expect(next).toBeEnabled();
    expect(screen.getAllByText("Hva Emnedesign ikke endrer")).toHaveLength(1);
  });

  it("explains Blueprint once for the selection, with details on request", async () => {
    stub((m) => full(m, { blueprint: ASSOCIATED }));
    const user = userEvent.setup();
    render(wrap(<CourseDesign />));
    const summary = await screen.findByRole("region", { name: "Dette blir berørt" });
    expect(within(summary).getByText(ASSOCIATED.summary)).toBeInTheDocument();
    expect(within(summary).getByText(ASSOCIATED.limitation)).toBeInTheDocument();
    expect(within(summary).queryByText(/Elementet er ikke låst/)).toBeNull();
    await user.click(within(summary).getByText("Se Blueprint-detaljer"));
    expect(within(summary).getByText(ASSOCIATED.details[0])).toBeVisible();
  });

  it("lets the teacher pick a module, explains what it means and keeps the choice when going back", async () => {
    stub(full);
    const user = userEvent.setup();
    render(wrap(<CourseDesign />));
    await user.click(screen.getByRole("radio", { name: /Én modul/ }));
    const next = screen.getByRole("button", { name: "Neste: velg design" });
    expect(next).toBeDisabled();
    expect(next).toHaveAccessibleDescription("Velg en modul først.");
    const picker = await screen.findByRole("group", { name: "Velg modul" });
    expect(within(picker).getByText("2 moduler")).toBeInTheDocument();
    expect(within(picker).getByText("4 elementer, 2 kan få design")).toBeInTheDocument();
    expect(within(picker).queryByLabelText("Søk etter modul"), "two modules need no search").toBeNull();
    await user.click(within(picker).getByText("Modul 1"));
    expect(within(picker).getByRole("radio", { name: /Modul 1/ })).toBeChecked();
    const summary = await screen.findByRole("region", { name: "Dette blir berørt" });
    expect(within(summary).getByText(/: 4 elementer i modulen, 2 kan få design\./)).toBeInTheDocument();
    expect(within(summary).getByText(/1 element brukes også i andre moduler \(«Intro»\)\. Endringen gjelder det delte innholdet/)).toBeInTheDocument();
    await waitFor(() => expect(next).toBeEnabled());
    await user.click(next);
    expect(await screen.findByRole("heading", { name: "Velg design" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tilbake: omfang" }));
    expect(screen.getByRole("radio", { name: /Én modul/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Modul 1/ })).toBeChecked();
  });

  it("never shows the previous module's figures while the new one loads", async () => {
    let release: (value: { body: unknown }) => void = () => {};
    stub((moduleId) => (moduleId === "202" ? new Promise((resolve) => { release = resolve; }) : full(moduleId)));
    const user = userEvent.setup();
    render(wrap(<CourseDesign />));
    await user.click(screen.getByRole("radio", { name: /Én modul/ }));
    await user.click(await screen.findByRole("radio", { name: /Modul 1/ }));
    expect(await screen.findByText(/2 innholdselementer – inkludert 1/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Modul 2/ }));
    expect(await screen.findByText("Leser innholdet fra Canvas …")).toBeInTheDocument();
    expect(screen.queryByText(/2 innholdselementer/)).toBeNull();
    expect(screen.getByRole("button", { name: "Neste: velg design" })).toHaveAccessibleDescription("Venter på innholdet fra Canvas …");
    release(full("202"));
    expect(await screen.findByText("1 innholdselement")).toBeInTheDocument();
  });

  it("searches many modules by name, counts hits and offers to clear an empty search", async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ id: String(300 + i), name: `Uke ${i + 1}`, position: i + 1, published: true, count: i, total: i + 1 }));
    stub(() => ({ body: { ...full(null).body, modules: many } }));
    const user = userEvent.setup();
    render(wrap(<CourseDesign />));
    await user.click(screen.getByRole("radio", { name: /Én modul/ }));
    const picker = await screen.findByRole("group", { name: "Velg modul" });
    expect(within(picker).getByText("12 moduler")).toBeInTheDocument();
    const search = within(picker).getByRole("searchbox", { name: "Søk etter modul" });
    expect(search).toHaveAttribute("placeholder", "Søk etter modulnavn …");
    await user.type(search, "uke 1");
    expect(within(picker).getAllByRole("radio").map((r) => (r as HTMLInputElement).value), "Uke 1, 10, 11 and 12 in Canvas' order")
      .toEqual(["300", "309", "310", "311"]);
    expect(within(picker).getByText("4 treff")).toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "finnes ikke");
    expect(within(picker).getByText("Ingen moduler passer søket «finnes ikke».")).toBeInTheDocument();
    await user.click(within(picker).getByRole("button", { name: "Tøm søket" }));
    expect(within(picker).getAllByRole("radio")).toHaveLength(12);
  });

  it("shows errors with «Prøv igjen», missing access and nothing to design", async () => {
    let attempt = 0;
    stub(() => (++attempt === 1 ? { status: 500, body: { error: { code: "internal_error", message: "Canvas svarte ikke." } } } : full(null)));
    const user = userEvent.setup();
    const { unmount } = render(wrap(<CourseDesign />));
    expect(await screen.findByText("Kunne ikke lese innholdet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Neste: velg design" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Prøv igjen" }));
    expect(await screen.findByRole("region", { name: "Dette blir berørt" })).toBeInTheDocument();
    unmount();

    stub(() => ({ status: 403, body: { error: { code: "canvas_forbidden", message: "Du mangler tilgang til dette i Canvas." } } }));
    const second = render(wrap(<CourseDesign />));
    expect(await screen.findByText("Mangler tilgang i Canvas")).toBeInTheDocument();
    second.unmount();

    stub(() => ({ body: { ...full(null).body, items: [], not_included: [{ label: "Filer (2)", reason: "Ikke innhold." }] } }));
    render(wrap(<CourseDesign />));
    expect(await screen.findByText("Ikke noe som kan få design")).toBeInTheDocument();
    expect(screen.getByText(/Ikke med: Filer \(2\)\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Neste: velg design" })).toHaveAccessibleDescription("Det er ikke noe som kan få design i omfanget.");
  });

  it("shows a small example from the top of a page and a larger one in a dialog that returns focus", async () => {
    stub(full);
    const user = userEvent.setup();
    render(wrap(<CourseDesign />));
    const example = await screen.findByRole("complementary", { name: "Eksempel på design" });
    expect(within(example).getByText(/Eksempelinnhold i designet «Akademisk» – ikke ditt emne og ikke et valg/)).toBeInTheDocument();
    const small = example.querySelector("iframe")!;
    expect(small).toHaveAttribute("aria-hidden", "true");
    expect(small).toHaveAttribute("tabindex", "-1");
    expect(small.getAttribute("srcdoc")).toContain("Uke 3: Tilbakemelding");
    expect(small.getAttribute("srcdoc")).toContain("overflow: hidden");
    const open = within(example).getByRole("button", { name: "Se større eksempel" });
    await user.click(open);
    const dialog = screen.getByRole("dialog", { name: "Eksempel på design" });
    expect(within(dialog).getByTitle("Eksempel på design: Akademisk (eksempelinnhold)").getAttribute("srcdoc")).toContain("Hele eksemplet");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("starts again from the scope when another course is chosen", async () => {
    stub(full);
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const tree = () => (
      <QueryClientProvider client={client}>
        <ToastProvider><UiProvider><MemoryRouter><CourseDesign /></MemoryRouter></UiProvider></ToastProvider>
      </QueryClientProvider>
    );
    const { rerender } = render(tree());
    await user.click(screen.getByRole("radio", { name: /Én modul/ }));
    await user.click(await screen.findByRole("radio", { name: /Modul 1/ }));
    const next = screen.getByRole("button", { name: "Neste: velg design" });
    await waitFor(() => expect(next).toBeEnabled());
    await user.click(next);
    expect(await screen.findByRole("heading", { name: "Velg design" })).toBeInTheDocument();
    course.id = "102";
    rerender(tree());
    await waitFor(() => expect(screen.getByRole("heading", { name: "Velg omfang" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Neste: velg design" })).toHaveAccessibleDescription("Velg en modul først.");
  });
});

describe("top bar in Emnedesign", () => {
  it("shows no analysis button on Emnedesign (it has no analysis of its own) and «Analyser hele emnet» on Oversikt", () => {
    stub(full);
    const { unmount } = render(wrap(<RunAnalysisButton />, "/emnedesign"));
    expect(screen.queryByRole("button", { name: /^Analyser/ })).toBeNull();
    unmount();
    render(wrap(<RunAnalysisButton />, "/oversikt"));
    const main = screen.getByRole("button", { name: "Analyser hele emnet" });
    expect(main).toHaveClass("ek-btn--primary");
    expect(main).toHaveClass("ek-header__analyse");
  });
});

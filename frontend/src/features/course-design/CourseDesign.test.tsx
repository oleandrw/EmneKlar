import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PRIMARY_NAV } from "../../core/layout/nav";
import { UiProvider } from "../../core/ui";
import { ToastProvider } from "../../design-system";
import { CourseDesign, CourseDesignPage } from "./CourseDesign";

const session = vi.hoisted(() => ({ flags: {} as Record<string, boolean> }));
vi.mock("../../core/session", () => ({
  useSession: () => ({ canvas: { token_configured: true }, ai: { providers_enabled: [] }, flags: session.flags, general: { page_size: 25 } }),
}));
vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

const profile = (id: string, label: string, isDefault = false) => ({
  id, version: "1", label, description: `${label} beskrivelse`, default: isDefault, tokens: {},
  sample_keep: `<div class="ek-design">${label}</div>`, sample_structure: `<div class="ek-design"><div class="ek-design-box">${label}</div></div>`,
});
const item = (key: string, title: string, kind: string, extra: object = {}) => ({
  key, object_type: key.split(":")[0], object_id: key.split(":")[1], title, kind, kind_label: kind, modules: [], shared: false,
  locked: false, published: true, design: null, empty: false, excluded: false, url: null, ...extra,
});
const INVENTORY = {
  modules: [{ id: "202", name: "Modul 2" }],
  items: [
    item("page:forside", "Forside", "front_page"),
    item("page:velkommen", "Velkommen", "module_intro", { modules: ["Modul 1", "Modul 2"], shared: true }),
    item("assignment:301", "Innlevering 1", "assignment", { locked: true }),
  ],
  not_included: [{ label: "New Quizzes (1)", reason: "Eget API." }],
  where: { role: "associated", message: "Innholdet kommer fra et Blueprint-emne." },
  blueprint: { role: "associated", summary: "Emnet er knyttet til Blueprint-emnet «BP». 1 av 3 elementer i utvalget er låst derfra.",
    limitation: "1 av 3 elementer er låst fra Blueprint-emnet og må trolig endres der.", details: [], locked: 1, total: 3 },
  course: { name: "Emne" },
};

function stub() {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    let data: unknown = {};
    if (url.endsWith("/api/course-design/profiles")) {
      data = { profiles: [profile("akademisk", "Akademisk", true), profile("gronn-akademi", "Grønn akademi")], default: "akademisk" };
    } else if (url.endsWith("/course-design")) data = { design: null, excluded: [] };
    else if (url.includes("/course-design/inventory")) data = INVENTORY;
    else if (url.endsWith("/course-design/preview")) {
      data = { items: (body as { items: string[] }).items.map((key) => ({ key, content_hash: `h-${key}`, before: "<p>før</p>",
        after: "<div class=\"ek-design\"><p>etter</p></div>", notes: [], structure_changes: [], problems: [], unchanged: false })) };
    } else if (url.endsWith("/course-design/approve")) {
      data = { results: (body as { items: { key: string }[] }).items.map((i, n) => ({ key: i.key, status: "approved", change_id: n + 1 })) };
    }
    return new Response(JSON.stringify(data), { status: 200 });
  }));
  return calls;
}

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider><UiProvider><MemoryRouter>{children}</MemoryRouter></UiProvider></ToastProvider>
    </QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  session.flags = {};
});

describe("Emnedesign", () => {
  it("is in the main menu where Emneforside was, and Emneforside is gone", () => {
    expect(PRIMARY_NAV.map((n) => n.label)).toEqual([
      "Oversikt", "Universell utforming", "Innholdskvalitet", "Emnestruktur", "Quizassistent", "Emnedesign", "Canvas-verktøy", "Rapporter"]);
    expect(PRIMARY_NAV.find((n) => n.label === "Emnedesign")).toMatchObject({ to: "/emnedesign", flag: "course_design" });
  });

  it("explains when the feature is turned off and asks Canvas for nothing", () => {
    const calls = stub();
    session.flags = { course_design: false };
    render(wrap(<CourseDesignPage />));
    expect(screen.getByRole("heading", { level: 1, name: "Emnedesign" })).toBeInTheDocument();
    expect(screen.getByText("Emnedesign er slått av")).toBeInTheDocument();
    expect(document.title).toBe("Emnedesign – EmneKlar");
    expect(calls).toEqual([]);
  });

  it("goes from scope to design to preview and approves to the change queue", async () => {
    const calls = stub();
    const user = userEvent.setup();
    render(wrap(<CourseDesign />));
    expect(screen.getByRole("radio", { name: /Hele emnet/ })).toBeChecked();
    const next = screen.getByRole("button", { name: "Neste: velg design" });
    await waitFor(() => expect(next, "enabled once the content is read").toBeEnabled());
    await user.click(next);

    expect(await screen.findByRole("radio", { name: /Akademisk \(standard\)/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Behold oppbyggingen \(standard\)/ })).toBeChecked();
    expect(screen.getByTitle("Eksempelinnhold med designet Akademisk")).toHaveAttribute("sandbox", "");
    await user.click(screen.getByRole("radio", { name: /Grønn akademi/ }));
    await user.click(screen.getByRole("button", { name: "Neste: forhåndsvis" }));

    const list = await screen.findByRole("list", { name: "Innhold i omfanget" });
    expect(within(list).getByText(/Brukt i 2 moduler \(Modul 1, Modul 2\)/)).toBeInTheDocument();
    expect(within(list).getByText(/Låst fra Blueprint-emnet. Canvas avgjør ved publisering/)).toBeInTheDocument();
    expect(screen.getByText(/Emnet er knyttet til Blueprint-emnet «BP». 1 av 3 elementer i utvalget er låst derfra./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Neste: godkjenn" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Lag forhåndsvisning (3)" }));
    await waitFor(() => expect(within(list).getAllByText("Klar")).toHaveLength(3));
    await user.click(within(list).getAllByRole("button", { name: "Vis før og etter" })[0]);
    expect(screen.getByTitle("Før: Forside")).toHaveAttribute("sandbox", "");
    expect(screen.getByTitle("Etter: Forside")).toBeInTheDocument();
    expect(screen.getByText("Bare stilendringer: tekst, rekkefølge og seksjoner er som før.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Neste: godkjenn" }));
    await user.click(screen.getByRole("button", { name: "Godkjenn 3 forslag til endringskøen" }));
    expect(await screen.findByText("3 forslag er godkjent i endringskøen")).toBeInTheDocument();
    const approve = calls.find((c) => c.url.endsWith("/course-design/approve"))?.body as { profile_id: string; items: { key: string; content_hash: string; plan: unknown }[] };
    expect(approve.profile_id).toBe("gronn-akademi");
    expect(approve.items.map((i) => [i.key, i.content_hash, i.plan])).toEqual([
      ["page:forside", "h-page:forside", null], ["page:velkommen", "h-page:velkommen", null], ["assignment:301", "h-assignment:301", null]]);
    expect(calls.some((c) => c.url.includes("/api/changes/apply")), "nothing is published from Emnedesign").toBe(false);
  });
});
